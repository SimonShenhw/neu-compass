"""scripts/export_openapi.py (R2b): web/openapi.json is the API's OpenAPI document byte for byte, and the web front
end's generated types (web/src/api/schema.ts) come from it. Built in process: no server, model or database.

中文：web/openapi.json 要和 API 的 OpenAPI 文档逐字节一致，新前端生成的类型就从它来。在进程里生成，不起服务、
不加载模型、不连数据库。"""

import importlib
import json
from pathlib import Path

from config import settings

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "web" / "openapi.json"


def exporter():
    return importlib.import_module("scripts.export_openapi")


def test_the_committed_document_is_current():
    # What CI's `--check` step checks; a route or model changed without a new export fails here first.
    # 中文：和 CI 的 `--check` 查的一样；改了路由或模型却没重新导出，这里先红。
    assert COMMITTED.read_bytes().decode("utf-8") == exporter().openapi_text()


def test_the_text_is_stable_sorted_and_ends_in_one_lf():
    text = exporter().openapi_text()
    assert exporter().openapi_text() == text
    assert text.endswith("}\n") and not text.endswith("\n\n") and "\r" not in text
    document = json.loads(text)
    assert json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n" == text
    assert document["openapi"].startswith("3.1.")
    assert "数据与隐私" in text  # Chinese stays readable, not \u escapes. 中文不转成 \u 转义。


def test_settings_that_differ_between_machines_do_not_change_it(monkeypatch):
    before = exporter().openapi_text()
    monkeypatch.setattr(settings, "web_origins", ["https://compass.example.test"])
    monkeypatch.setattr(settings, "answer_feedback_enabled", not settings.answer_feedback_enabled)
    monkeypatch.setattr(settings, "request_guard_enabled", not settings.request_guard_enabled)
    monkeypatch.setattr(settings, "query_log_retention_days", 30)
    assert exporter().openapi_text() == before


def test_write_and_check(tmp_path, capsys):
    module = exporter()
    out = tmp_path / "openapi.json"
    assert module.main(["--check", "--out", str(out)]) == 1  # missing 中文：文件不存在
    assert not out.exists()
    assert module.main(["--out", str(out)]) == 0
    assert out.read_bytes() == module.openapi_text().encode("utf-8")
    assert module.main(["--check", "--out", str(out)]) == 0
    assert "up to date" in capsys.readouterr().out
    for stale in (module.openapi_text() + "\n", module.openapi_text().replace("\n", "\r\n"),
                  module.openapi_text().replace('"3.1.', '"3.0.', 1)):
        out.write_bytes(stale.encode("utf-8"))
        assert module.main(["--check", "--out", str(out)]) == 1
        assert out.read_bytes() == stale.encode("utf-8")  # --check writes nothing. 中文：--check 不写文件。
        assert "out of date" in capsys.readouterr().err


def test_every_success_but_the_chat_stream_has_a_typed_body():
    # The generated types are only as good as the response models. The chat stream is NDJSON; its events are typed by
    # hand in the front end (docs/api_contract.md). 中文：生成的类型取决于响应模型；聊天流是 NDJSON，事件类型在前端手写。
    document = json.loads(exporter().openapi_text())
    untyped = [f"{method.upper()} {path} {status} {media}"
               for path, item in document["paths"].items()
               for method, operation in item.items()
               for status, response in operation["responses"].items() if status.startswith("2")
               for media, content in response.get("content", {}).items() if not (content or {}).get("schema")]
    assert untyped == ["POST /chat 200 application/json", "POST /chat 200 application/x-ndjson"]
