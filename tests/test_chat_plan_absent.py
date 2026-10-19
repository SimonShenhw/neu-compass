"""Frozen pre-F bytes: a missing plan does not change metadata or course evidence.
中文：只排除非确定耗时与必然升级的提示词版本；其余不放宽或重生成基线。
"""

import hashlib
import json
from pathlib import Path


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
    for key, response in zip(keys, responses, strict=True):
        expected = frozen["turns"][key]
        assert response.status_code == expected["http_status"]
        if response.status_code != 200:
            assert response.json()["detail"] == expected["detail"]
            continue
        meta = json.loads(response.text.splitlines()[0])
        meta.pop("retrieval_ms")
        assert meta.pop("prompt_version") in {"4.4", "4.5"}
        assert "plan_context" not in meta
        assert hashlib.sha256(json.dumps(meta, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == expected["meta_sha256"], key
        block = next(prompt_iter).split("# Retrieved course evidence (JSON DATA)\n", 1)[1].rsplit("\n\nAnswer:", 1)[0].strip()
        assert hashlib.sha256(block.encode()).hexdigest() == expected["course_block_sha256"], key
    assert next(prompt_iter, None) is None
