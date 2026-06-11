"""Thin httpx wrapper around the FastAPI backend.

Streamlit pages use this instead of constructing requests inline so:
- tests can mock transport via httpx.MockTransport (no live server needed)
- timeouts / auth headers / base URL live in one place
- the public surface mirrors the backend route set, one method per route

Usage from a Streamlit page:
    from app.api_client import ApiClient
    with ApiClient(user_id=state["user_id"]) as api:
        body = api.search(query, k=10)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from config import settings


class ApiError(RuntimeError):
    """Non-2xx response from the API. .status_code + .detail are exposed
    for the UI to render a useful message."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"API {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class ApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        user_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        # 30s default: the NAS OpenVINO path runs /search at p50 ~2.3s but the
        # ONNX-CPU fallback is 7-10s — the old 10s default turned a degraded
        # backend into raw ReadTimeout tracebacks in the Streamlit UI.
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        headers: dict[str, str] = {}
        if user_id:
            headers["X-User-Id"] = user_id
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    # === Context manager so callers can `with ApiClient() as api:` ===

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # === Auth (X-User-Id is the Week 6 OAuth stub; see api/routes/coop.py) ===

    def set_user_id(self, user_id: str | None) -> None:
        if user_id:
            self._client.headers["X-User-Id"] = user_id
        else:
            self._client.headers.pop("X-User-Id", None)

    # === Routes ===

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def ready(self) -> dict[str, Any]:
        return self._get("/ready")

    def search(
        self,
        query: str,
        *,
        k: int = 10,
        term: str | None = None,
        credits: int | None = None,
        delivery_mode: str | None = None,
        professor: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query, "k": k}
        if term:
            body["term"] = term
        if credits is not None:
            body["credits"] = credits
        if delivery_mode:
            body["delivery_mode"] = delivery_mode
        if professor:
            body["professor"] = professor
        return self._post("/search", body)

    def get_course(self, course_id: str) -> dict[str, Any]:
        return self._get(f"/course/{course_id}")

    def list_coop(self) -> list[dict[str, Any]]:
        return self._get("/coop")

    def upload_coop(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/coop", payload)

    # === OAuth callback ===

    def oauth_callback(
        self,
        code: str,
        *,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"code": code}
        if redirect_uri:
            body["redirect_uri"] = redirect_uri
        return self._post("/auth/callback", body)

    # === Chat (streaming) ===

    def chat_stream(
        self,
        body: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        """Iterate over /chat NDJSON events.

        Each yield is a parsed dict with shape
        {"type": "meta"|"token"|"error"|"done", ...}. Caller renders
        accordingly (Streamlit st.write_stream consumes the `text` from
        token events; meta is stashed for evidence bubbles).

        Raises ApiError if the server returns non-200 BEFORE streaming
        starts. Errors mid-stream surface as in-stream `error` events,
        not exceptions — so the caller still gets the partial output.
        """
        with self._client.stream("POST", "/chat", json=body) as resp:
            if resp.status_code >= 400:
                resp.read()
                self._unwrap(resp)  # raises ApiError
            for raw_line in resp.iter_lines():
                line = raw_line.strip() if isinstance(raw_line, str) else raw_line
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Malformed line — skip rather than break the whole stream.
                    continue

    # === Internal ===

    def _get(self, path: str) -> Any:
        try:
            return self._unwrap(self._client.get(path))
        except httpx.TimeoutException as e:
            raise ApiError(504, f"API timed out: {type(e).__name__}") from e

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        try:
            return self._unwrap(self._client.post(path, json=body))
        except httpx.TimeoutException as e:
            raise ApiError(504, f"API timed out: {type(e).__name__}") from e

    @staticmethod
    def _unwrap(r: httpx.Response) -> Any:
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise ApiError(r.status_code, str(detail))
        if r.status_code == 204:
            return None
        return r.json()


__all__ = ["ApiClient", "ApiError"]
