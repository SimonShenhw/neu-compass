"""Fixed synthetic inputs for all ten curated rule documents, never real credit claims."""

import json
from pathlib import Path

from schemas.plan_draft import DraftCourse, evaluate_draft
from schemas.program_plan import ProgramPlan

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests/fixtures/plan_draft_seed.json"
SEEDS = ("boston_2026_2027_core_fragments.json", "boston_2026_2027_extended_rules.json", "boston_2026_2027_pathway_rules.json")


def seed_documents():
    return [(name, ProgramPlan.model_validate(raw)) for name in SEEDS
            for raw in json.loads((ROOT / "data/program_plan_seed" / name).read_text(encoding="utf-8"))]


def synthetic_courses(plan):
    if plan.program_id == "cs-ms":
        codes = ["CS 5001", "CS 5003", "CS 5004", "CS 5005", "CS 5006", "CS 5007", "CS 5002",
                 "CS 5010", "CS 5800", "CS 6140", "CS 6240", "CS 7180"]
    elif plan.program_id == "ds-ms":
        codes = ["DS 5110", "DS 5220", "EECE 7205", "CS 6140", "EECE 5360", "DS 5500", "DS 7995", "CS 5800"]
    else:
        codes = ["INFO 5100", "INFO 6210", "INFO 6205", "INFO 6105", "CSYE 6220", "INFO 5200", "INFO 5001", "INFO 7999", "CS 5800"]
    return [DraftCourse(course_id="synthetic-" + code.replace(" ", "-"), code=code, name="Synthetic " + code,
        credits=None if code in {"CS 7180", "DS 7995", "INFO 5001"} else 12 if code == "EECE 5360" else 0 if code == "CS 5002" else 4)
        for code in codes]


def snapshot_text():
    records = [{"seed": name, "plan_id": plan.plan_id, "data_kind": "synthetic_only_not_real_transcript",
        "courses": [c.model_dump() for c in synthetic_courses(plan)],
        "result": evaluate_draft(plan, synthetic_courses(plan)).model_dump()} for name, plan in seed_documents()]
    return json.dumps(records, ensure_ascii=False, indent=2) + "\n"
