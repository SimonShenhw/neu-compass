"""Known pathway differences; no inferred personal waivers or enrollment."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from schemas.program_plan import ProgramPlan
from schemas.program_source import SourceCapture
from scripts.audit_program_rule_sources import audit_plan
from db.connection import connect
from db.program_plan_repository import ProgramPlanRepository
from db.program_repository import ProgramRepository
from schemas.program import Program
from scripts.init_db import init_database

ROOT = Path(__file__).resolve().parent.parent
PATHWAYS = ROOT / "data/program_plan_seed/boston_2026_2027_pathway_rules.json"


def documents():
    return json.loads(PATHWAYS.read_text(encoding="utf-8"))


def fake_source(tmp_path, index):
    """Small synthetic input for adapter tests, not official page reproduction."""
    data = documents()[index]
    plan = ProgramPlan.model_validate(data)
    title = plan.source_title.removesuffix(", 2026-2027 Edition")
    source = f'<h1>{title}</h1><p>2026-2027 Edition</p>'
    if index == 0:
        breadth, elective = plan.requirements.children[2:4]
        tables = [
            ("Align Bridge Coursework", ["CS 5001 and CS 5003 Pair 4", "CS 5002 Single 4", "CS 5004 and CS 5005 Pair 4", "CS 5008 and CS 5009 Pair 4"]),
            ("Core Requirements", ["CS 5800 Algorithms 4"]),
            ("Breadth Areas", ["Select three courses from at least two of the three following breadth areas: 12"] + [text for name, codes in breadth.areas.items() for text in [name, *codes]]),
            ("Electives", ["Complete 12 semester hours from the following: 12", *elective.course_codes, "CS 5100 to CS 7980"]),
        ]
    else:
        tables = [
            ("Core Requirements", ["INFO 5001 Single 4", "INFO 5100 and INFO 5101 Pair 4", "INFO 6215 Single 4"]),
            ("Restricted Electives", ["Complete 12 semester hours from the following: 12", "DAMG 6210", "INFO 6150", "INFO 6205", "INFO 6245", "INFO 6255", "INFO 6350", "INFO 7245", "INFO 7385"]),
            ("Electives", ["Complete 12 semester hours from the following: 12", "CSYE (except CSYE 6220)", "DAMG", "INFO", "MUST 5510", "MUST 5520", "MUST 6603", "TELE"]),
            ("Optional Co-op Experience", ["ENCP 6000 Prepare 1", "ENCP 6964 Work 0", "or ENCP 6954", "or ENCP 6955", "or ENCP 6965"]),
        ]
    for heading, rows in tables:
        source += f'<h2>{heading}</h2><table class="sc_courselist">' + ''.join(f'<tr><td>{row}</td></tr>' for row in rows) + '</table>'
    content = source.encode()
    digest = hashlib.sha256(content).hexdigest()
    data["source_html_sha256"] = digest
    plan = ProgramPlan.model_validate(data)
    metadata = SourceCapture(url=plan.source_url, catalog_year=plan.catalog_year, captured_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        sha256=digest, byte_count=len(content), page_title=title)
    (tmp_path / f"{digest}.html").write_bytes(content)
    (tmp_path / f"{digest}.json").write_text(metadata.model_dump_json(), encoding="utf-8")
    return plan


@pytest.mark.parametrize("index", [0, 1])
def test_pathway_source_audit_accepts_specific_bridge_groups(tmp_path, index):
    plan = fake_source(tmp_path, index)
    result = audit_plan(plan, tmp_path)
    assert result["coverage"] == "partial"
    assert any("bridge" in item.lower() or "core" in item.lower() for item in result["checks"])


def test_pathway_bundle_has_independent_scope_and_matching_frozen_source_manifest():
    plans = [ProgramPlan.model_validate(item) for item in documents()]
    assert [(plan.program_id, plan.pathway) for plan in plans] == [("cs-ms", "align"), ("info-ms", "bridge")]
    assert all(plan.coverage == "partial" and plan.concentration is None for plan in plans)
    assert all(plan.campus == "boston" and plan.catalog_year == "2026-2027" for plan in plans)
    metadata = [SourceCapture.model_validate(item) for item in json.loads((PATHWAYS.parent / "boston_2026_2027_pathway_source_manifest.json").read_text(encoding="utf-8"))]
    by_hash = {item.sha256: item for item in metadata}
    assert len(by_hash) == 2
    for plan in plans:
        source = by_hash[plan.source_html_sha256]
        assert (source.url, source.catalog_year, source.captured_at.date()) == (plan.source_url, plan.catalog_year, plan.captured_on)


def test_align_preserves_bridge_pairs_grade_exception_and_different_core():
    plan = ProgramPlan.model_validate(documents()[0])
    bridge = plan.requirements.children[0]
    assert bridge.kind == "all_of"
    assert [node.course_code for node in bridge.children[0].children] == ["CS 5001", "CS 5003"]
    assert bridge.children[1].course_code == "CS 5002"
    assert [node.course_code for node in bridge.children[2].children] == ["CS 5004", "CS 5005"]
    assert [node.course_code for node in bridge.children[3].children] == ["CS 5008", "CS 5009"]
    assert "B 或以上" in bridge.children[4].label and "项目确定" in bridge.children[4].label
    assert plan.requirements.children[1].course_code == "CS 5800"
    assert "36–44" in plan.requirements.children[4].label
    assert not any(node.course_code in {"CS 5010", "CS 5011"} for node in bridge.children)


def test_info_bridge_does_not_copy_standard_exit_or_5200_exclusion():
    plan = ProgramPlan.model_validate(documents()[1])
    core, restricted, elective = plan.requirements.children[:3]
    assert [node.course_code for node in core.children if node.kind == "course"] == ["INFO 5001", "INFO 6215"]
    assert [node.course_code for node in core.children[1].children] == ["INFO 5100", "INFO 5101"]
    assert "C 或以上" in core.children[-1].label and "更高成绩" in core.children[-1].label
    assert (restricted.min_credits, len(restricted.course_codes), elective.min_credits) == (12, 8, 12)
    assert restricted.subject_codes == [] and elective.subject_codes == ["CSYE", "DAMG", "INFO", "TELE"]
    assert elective.excluded_course_codes == ["CSYE 6220"]
    assert not any(node.kind == "any_of" for node in plan.requirements.children)
    assert "36 学分" in plan.requirements.children[3].label and "37 学分" in plan.requirements.children[3].label
    assert plan.requirements.children[4].kind == "optional"


@pytest.mark.parametrize("tamper", ["align-or", "align-lab", "align-standard-core", "bridge-restricted", "bridge-exclusion", "bridge-coop-and"])
def test_pathway_source_audit_rejects_semantic_copy_or_pair_loss(tmp_path, tamper):
    index = 0 if tamper.startswith("align") else 1
    plan = fake_source(tmp_path, index)
    data = plan.model_dump(mode="json")
    children = data["requirements"]["children"]
    if tamper == "align-or":
        children[0]["children"][0]["kind"] = "any_of"
    elif tamper == "align-lab":
        children[0]["children"][0] = {"kind": "course", "label": "Missing recitation", "course_code": "CS 5001"}
    elif tamper == "align-standard-core":
        children[1]["course_code"] = "CS 5010"
    elif tamper == "bridge-restricted":
        children[1]["course_codes"].append("INFO 5200")
    elif tamper == "bridge-exclusion":
        children[2]["excluded_course_codes"].append("INFO 5200")
    else:
        children[4]["children"][0]["children"][1]["kind"] = "all_of"
    with pytest.raises(ValueError):
        audit_plan(ProgramPlan.model_validate(data), tmp_path)


@pytest.mark.parametrize("family,pathway,other", [("cs-ms", "align", "bridge"), ("info-ms", "bridge", "align")])
def test_api_pathway_filters_do_not_fall_back_to_standard(api_client, empty_db, family, pathway, other):
    ProgramRepository(empty_db).add_program(Program(program_id=family, full_name=family, prefix=family.split("-")[0].upper()))
    standard = json.loads((PATHWAYS.parent / "boston_2026_2027_extended_rules.json").read_text(encoding="utf-8"))
    repo = ProgramPlanRepository(empty_db)
    all_docs = [item for item in [*standard, *documents()] if item["program_id"] == family]
    for item in all_docs:
        repo.store(ProgramPlan.model_validate(item))
    scoped = api_client.get(f"/programs/{family}/plans", params={"pathway": pathway}).json()["plans"]
    assert len(scoped) == 1 and scoped[0]["pathway"] == pathway
    assert api_client.get(f"/programs/{family}/plans", params={"pathway": other}).json()["plans"] == []
    assert [item["pathway"] for item in api_client.get(f"/programs/{family}/plans", params={"pathway": "standard"}).json()["plans"]] == ["standard"]
    assert api_client.get(f"/programs/{family}").json()["semesters"] == []
    from api.dependencies import get_chat_stream_fn  # noqa: PLC0415
    api_client.app.dependency_overrides[get_chat_stream_fn] = lambda: (lambda prompt: iter(["ok"]))
    response = api_client.post("/chat", json={"query": "first semester", "program_id": family})
    assert response.status_code == 200
    meta = json.loads(response.text.splitlines()[0])
    # Never turn bridge groups into a schedule: no program route, explicit notice.
    assert meta["matched_via"] != "program"
    assert meta["notices"] == ["program_schedule_unverified"]


def test_pathway_real_cli_is_additive_readonly_and_idempotent(tmp_path):
    path, file = tmp_path / "runtime.db", tmp_path / "plans.json"
    init_database(path)
    conn = connect(path)
    for family in ["cs-ms", "info-ms"]:
        ProgramRepository(conn).add_program(Program(program_id=family, full_name="Family", prefix=family.split("-")[0].upper()))
    standard = json.loads((PATHWAYS.parent / "boston_2026_2027_core_fragments.json").read_text(encoding="utf-8"))
    for item in standard:
        if item["program_id"] != "ds-ms":
            ProgramPlanRepository(conn).store(ProgramPlan.model_validate(item))
    conn.commit()
    old = [tuple(row) for row in conn.execute("SELECT document FROM program_plans ORDER BY plan_id")]
    conn.close()
    plans = [fake_source(tmp_path, index).model_dump(mode="json") for index in [0, 1]]
    file.write_text(json.dumps(plans), encoding="utf-8")
    command = [sys.executable, str(ROOT / "scripts/sync_program_plans.py"), "--db-path", str(path),
               "--plan-file", str(file), "--source-dir", str(tmp_path)]
    before = path.read_bytes()
    for extra, expected in [([], 0), (["--commit"], 2), (["--commit"], 0)]:
        result = subprocess.run([*command, *extra], capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["stored"] == expected
        if not extra:
            assert before == path.read_bytes()
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM program_plans").fetchone()[0] == 4
    current = [tuple(row) for row in conn.execute("SELECT document FROM program_plans WHERE pathway='standard' ORDER BY plan_id")]
    assert current == old
    conn.close()


@pytest.mark.parametrize("index,label", [(0, "Align"), (1, "Bridge")])
def test_real_pathway_widget_preserves_scope_and_paired_courses(index, label):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import json
from pathlib import Path
import streamlit as st
import app.program_plan_view as view
root = Path(view.__file__).resolve().parent.parent
documents = json.loads((root / "data/program_plan_seed/boston_2026_2027_pathway_rules.json").read_text(encoding="utf-8"))
view.render_program_plans(st, documents, key="pathway-plan")
''').run(timeout=45)
    assert len(app.exception) == 0 and app.selectbox[0].value is None
    app.selectbox[0].set_value(documents()[index]["plan_id"]).run(timeout=45)
    assert len(app.exception) == 0
    assert any(label in item.value and "2026-2027" in item.value for item in app.caption)
    text = "\n".join(item.value for item in app.text)
    assert "未核验" in text and "全部分支（AND）" in text
    assert ("CS 5003" if index == 0 else "INFO 5101") in text
