"""Frozen pre-F bytes: a missing plan does not change metadata or course evidence. Only the non-deterministic time,
the prompt version (which must go up), 4.6's rename of the flat prerequisite lists and the program 409s' new selector
name (both undone before comparing, so the rest is still compared byte for byte) are left out; the baseline is never
regenerated.
中文：只排除非确定耗时、必然升级的提示词版本、4.6 对平铺先修列表的改名和项目 409 里选择框的新名字（比较前还原，其余仍逐字节比较）；
其余不放宽或重生成基线。
"""

import hashlib
import json
from pathlib import Path

# The program 409s name the web front end's 「项目」 where d7c5530 named the Streamlit page's selector (CONTENT-01,
# after R8 deleted the page): only that opening is put back; the rest of each detail is compared as it was frozen.
# 中文：项目 409 把 Streamlit 选择框的名字换成了新前端的「项目」；只还原开头这一段，其余照旧逐字比较。
SELECTOR_RENAMES = {
    "这个专业前缀对应多个项目，请先在「项目」里选择：": "这个专业前缀对应多个项目，请先在上方「你的项目（可选）」里选择：",
    "「项目」里选的项目与问题里的专业前缀不一致；": "上方「你的项目（可选）」选的项目与问题里的专业前缀不一致；",
}


def before_selector_rename(detail: str) -> str:
    """The detail with the selector's d7c5530 name back at its opening. 中文：开头换回 d7c5530 时选择框的名字。"""
    for new, old in SELECTOR_RENAMES.items():
        if detail.startswith(new):
            return old + detail[len(new):]
    return detail


def before_4_6(block: str) -> str:
    """The course block with 4.6's rename undone: each flat list back under its old name, in its place.
    中文：还原 4.6 的改名：每个平铺列表回到原来的名字和位置。"""
    from llm.prompts.chat_v4 import FLAT_PREREQS_KEY

    if block == "(no matches found in catalog)":
        return block

    def renamed(fields, name):
        return {(name if key == FLAT_PREREQS_KEY else key): value for key, value in fields.items()}

    records = json.loads(block)
    for record in records:
        record["recorded_metadata"] = renamed(record["recorded_metadata"], "prereqs")
        if record["answer_evidence"]["catalog"]:
            record["answer_evidence"]["catalog"] = renamed(record["answer_evidence"]["catalog"], "prereq_codes")
    return json.dumps(records, ensure_ascii=False, indent=2)


def test_all_unselected_turns_keep_the_base_meta_and_course_block_bytes(monkeypatch):
    import api.routes.chat as chat
    from eval.route_eval import run_eval
    from fastapi.testclient import TestClient

    frozen = json.loads((Path(__file__).parent / "fixtures/chat_no_plan_d7c5530.json").read_text())
    assert frozen["base_commit"] == "d7c5530a3707151ab53bad3ad3879f15d683c3f1"
    assert frozen["normalization"] == ["retrieval_ms", "prompt_version"]
    responses, prompts = [], []
    original_post, original_prompt = TestClient.post, chat.build_prompt

    def post(self, *args, **kwargs):
        response = original_post(self, *args, **kwargs)
        responses.append(response)
        return response

    def prompt(*args, **kwargs):
        text = original_prompt(*args, **kwargs)
        prompts.append(text)
        return text

    monkeypatch.setattr(TestClient, "post", post)
    monkeypatch.setattr(chat, "build_prompt", prompt)
    report = run_eval()
    assert report["status"] == "complete"
    keys = [f"{case['case_id']}:{index}" for case in report["cases"] for index in range(len(case["turns"]))]
    assert len(keys) == len(responses) == len(frozen["turns"]) == 53
    prompt_iter = iter(prompts)
    renamed = details_renamed = 0
    for key, response in zip(keys, responses, strict=True):
        expected = frozen["turns"][key]
        assert response.status_code == expected["http_status"]
        if response.status_code != 200:
            detail = response.json()["detail"]
            assert before_selector_rename(detail) == expected["detail"], key
            details_renamed += before_selector_rename(detail) != detail
            continue
        meta = json.loads(response.text.splitlines()[0])
        meta.pop("retrieval_ms")
        assert meta.pop("prompt_version") in {"4.4", "4.5", "4.6"}
        assert "plan_context" not in meta
        assert hashlib.sha256(json.dumps(meta, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == expected["meta_sha256"], key
        block = next(prompt_iter).split("# Retrieved course evidence (JSON DATA)\n", 1)[1].rsplit("\n\nAnswer:", 1)[0].strip()
        assert hashlib.sha256(before_4_6(block).encode()).hexdigest() == expected["course_block_sha256"], key
        renamed += before_4_6(block) != block
    assert next(prompt_iter, None) is None
    assert renamed  # The undoing is exercised: some of these blocks carry flat lists (26 of 49 at 4.6).
    assert details_renamed == 3  # Every 409 here is a program one: two ambiguous prefixes, one conflict.
