"""Bounded single-process admission for search/chat, with full-stream leases.

单进程总量门禁，不认 IP／代理头／token／eval 标签；不存查询，不排队。
ASGI 生命周期名额不是 GPU 任务强制取消、全局多 worker 配额或身份鉴权。
Importing this module does not load settings, databases or models.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import threading
import time


@dataclass(frozen=True)
class AdmissionPolicy:
    capacity: int = 8
    refill_per_second: float = 1.
    max_inflight: int = 2

    def __post_init__(self):
        if (type(self.capacity) is not int or not 1 <= self.capacity <= 10_000
                or type(self.max_inflight) is not int or not 1 <= self.max_inflight <= 100
                or isinstance(self.refill_per_second, bool)
                or not isinstance(self.refill_per_second, (int, float))
                or not math.isfinite(self.refill_per_second)
                or not .01 <= self.refill_per_second <= 1000):
            raise ValueError('invalid_admission_policy')


@dataclass(frozen=True)
class Denial:
    status_code: int
    error_type: str
    detail: str
    retry_after_seconds: int


class Lease:
    def __init__(self, guard):
        self._guard, self._released = guard, False

    def release(self):
        # Release does not need a working clock, including during exceptions.
        # 中文：释放不依赖时钟；多次调用或并发释放只扣一次名额。
        with self._guard._lock:
            if not self._released:
                self._guard._active -= 1
                self._released = True


class AdmissionGuard:
    def __init__(self, policy=None, *, clock=None):
        self.policy = policy if policy is not None else AdmissionPolicy()
        if not isinstance(self.policy, AdmissionPolicy):
            raise ValueError('invalid_admission_policy')
        self._clock = time.monotonic if clock is None else clock
        self._lock = threading.Lock()
        self._tokens, self._active = float(self.policy.capacity), 0
        self._last = None

    def acquire(self):
        with self._lock:
            now = self._clock()
            if (isinstance(now, bool) or not isinstance(now, (int, float))
                    or not math.isfinite(now) or now < 0
                    or self._last is not None and now < self._last):
                raise ValueError('invalid_admission_clock')
            if self._last is not None:
                self._tokens = min(float(self.policy.capacity),
                                   self._tokens + (now - self._last) * self.policy.refill_per_second)
            self._last = now
            # No queue and no token charge when the ASGI lifecycle slots are full.
            # 中文：先看并发名额；忙时不排队，也不扣速率额度。
            if self._active >= self.policy.max_inflight:
                return Denial(503, 'service_busy', 'Service busy. Retry manually later.', 1)
            if self._tokens < 1:
                retry = max(1, math.ceil((1 - self._tokens) / self.policy.refill_per_second))
                return Denial(429, 'rate_limited', 'Request rate exceeded. Retry manually later.', retry)
            self._tokens -= 1
            self._active += 1
            return Lease(self)

    def snapshot(self):
        """Local tests/diagnostics only; no HTTP endpoint, identifiers or persistence."""
        with self._lock:
            return dict(active=self._active, tokens=self._tokens)


class AdmissionMiddleware:
    def __init__(self, app, *, guard):
        if not isinstance(guard, AdmissionGuard):
            raise ValueError('invalid_admission_guard')
        self.app, self.guard = app, guard

    async def __call__(self, scope, receive, send):
        # Health/auth/read-only browsing stay available. Forwarding/eval headers
        # never exempt a request or create a new identity/bucket.
        # 中文：运维／认证／只读浏览不受此门禁；任何自报 header 不改变额度。
        if (scope['type'] != 'http' or scope.get('method') != 'POST'
                or scope.get('path', '').rstrip('/') not in {'/search', '/chat'}):
            return await self.app(scope, receive, send)
        try:
            result = self.guard.acquire()
        except Exception:
            result = Denial(503, 'service_unavailable', 'Admission unavailable. Retry manually later.', 1)
        if isinstance(result, Denial):
            body = json.dumps(dict(detail=result.detail, error_type=result.error_type,
                                   status_code=result.status_code)).encode('utf-8')
            await send({'type': 'http.response.start', 'status': result.status_code, 'headers': [
                (b'content-type', b'application/json'), (b'content-length', str(len(body)).encode('ascii')),
                (b'cache-control', b'no-store'),
                (b'retry-after', str(result.retry_after_seconds).encode('ascii'))]})
            await send({'type': 'http.response.body', 'body': body})
            return  # Never read body or invoke dependencies/model/DB on denial.
        try:
            # Pure ASGI: includes final body + stream cleanup, not just headers.
            # 中文：整个 app 调用期间持有名额，不能在流头发出后提前释放。
            await self.app(scope, receive, send)
        finally:
            result.release()
