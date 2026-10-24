"""A daily cap on model calls (batch T, policy P5: the user chose 200 a day on 10-21).

Every real Gemini call the API makes takes one place first: a chat answer, and a HyDE rescue that passed the
course-code guard. Evaluation through the API counts too; it costs the same. Offline scripts that call the model
through `llm` directly (evaluation, calibration, test-set and document generation, review enrichment) take no place
(A24 L7). The place is taken before the call, so a call that fails before it reaches Google still uses one. The count
is per UTC day and lives in `model_budget.json` next to the database, so a restart does not reset it, and no schema
change is needed. One API process serves the site (no uvicorn workers), so a process lock is enough; this is not a
multi-process or per-user quota. When the file cannot be read the count starts from 0; when it cannot be written the
count is still kept in memory and enforced, with one warning. The file is replaced atomically but not fsynced, so a
file left corrupt (for example by a power cut) restarts that day's count at 0. The cap is off when the limit is 0
(the code default; compose sets 200).

中文：模型调用的每日上限（T 批，政策 P5：用户 10-21 定为每天 200 次）。API 每次真正调用 Gemini 前先占一个名额：聊天
回答，以及通过了课号规则的 HyDE 救援。经过 API 的评测流量也算，花的是同一份钱；离线脚本通过 `llm` 直接调模型（评测、
校准、生成测试集和文档、评价富化），不占名额。名额在调用之前就占掉，所以还没到 Google 就失败的调用也用掉一个。按 UTC
日期计数，存在数据库同目录下的 `model_budget.json`，重启不归零，也不用改数据库结构。站点只有一个 API 进程（不开
uvicorn workers），所以进程锁就够了；这不是多进程或按用户的配额。文件读不了时从 0 开始数；写不了时仍在内存里计数并照样
限制，只记一次警告。文件是原子替换的，但没有 fsync，文件坏了（比如断电）当天就从 0 重数。上限为 0 时关闭（代码默认；
compose 设 200）。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger("neu_compass.model_budget")
FILENAME = "model_budget.json"


class ModelBudgetExhausted(Exception):
    """Raised by a budgeted model call when today's places are used up. 中文：今天的名额用完时由包了名额的调用抛出。"""


def _utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class ModelBudget:
    def __init__(self, path: Path, limit: int, *, today: Callable[[], str] = _utc_day) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("A model budget needs a limit of at least 1")
        self.path, self.limit, self._today = Path(path), limit, today
        self._lock = threading.Lock()
        self._day: str | None = None
        self._calls = 0
        self._loaded = False
        self._warned_write = False
        self._logged_exhausted: str | None = None

    def _load(self) -> None:
        self._loaded = True
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            day, calls = data["day"], data["calls"]
            if isinstance(day, str) and type(calls) is int and calls >= 0:
                self._day, self._calls = day, calls
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Missing or unreadable: start from 0. 中文：没有或读不了：从 0 开始。

    def _save(self) -> None:
        try:
            fd, tmp = tempfile.mkstemp(prefix=".model_budget.", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"day": self._day, "calls": self._calls}, f)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as exc:
            if not self._warned_write:
                self._warned_write = True
                log.warning("model_budget.write_failed", exc_type=type(exc).__name__)

    def acquire(self) -> bool:
        """Take one place for a model call that is about to happen; False when today's places are used up."""
        with self._lock:
            if not self._loaded:
                self._load()
            today = self._today()
            if self._day != today:
                self._day, self._calls = today, 0
            if self._calls >= self.limit:
                if self._logged_exhausted != today:
                    self._logged_exhausted = today
                    log.warning("model_budget.exhausted", day=today, limit=self.limit)
                return False
            self._calls += 1
            self._save()
            return True

    def used(self) -> int:
        with self._lock:
            if not self._loaded:
                self._load()
            return self._calls if self._day == self._today() else 0


__all__ = ["FILENAME", "ModelBudget", "ModelBudgetExhausted"]
