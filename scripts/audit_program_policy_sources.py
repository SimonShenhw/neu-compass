"""Offline exact-scope policy evidence audit; no network, DB or eligibility output."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.program_plan_repository import content_hash  # noqa: E402
from schemas.program_plan import ProgramPlan  # noqa: E402
from schemas.program_policy import ProgramPolicyBundle, verify_home_college, verify_policy_source  # noqa: E402
from schemas.program_source import verify_archived_source  # noqa: E402


def audit_bundle(bundle_file: Path, plan_files: list[Path], policy_source_dir: Path, program_source_dir: Path) -> dict:
    if bundle_file.stat().st_size > 300_000 or not 1 <= len(plan_files) <= 10:
        raise ValueError("Policy audit input outside size budget")
    bundle = ProgramPolicyBundle.model_validate_json(bundle_file.read_text(encoding="utf-8-sig"))
    plans, scopes = {}, set()
    for path in plan_files:
        if path.stat().st_size > 1_000_000:
            raise ValueError("Plan input outside size budget")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list) or not 1 <= len(payload) <= 100:
            raise ValueError("Expected a bounded nonempty plan array")
        for item in payload:
            plan = ProgramPlan.model_validate(item)
            if plan.plan_id in plans or plan.scope_key() in scopes:
                raise ValueError("Duplicate audit plan identity/scope")
            plans[plan.plan_id] = plan
            scopes.add(plan.scope_key())
    blocks = {p.policy_id: verify_policy_source(p, policy_source_dir) for p in bundle.policies}
    for link in bundle.links:
        plan = plans.get(link.plan_id)
        if (plan is None or plan.scope_key() != link.scope_key() or content_hash(plan) != link.plan_content_sha256
                or plan.review_status != "source_checked"):
            raise ValueError("Linked plan identity/scope/revision/review mismatch")
        if bundle.checked_on < plan.checked_on:
            raise ValueError("Policy association review predates plan review")
        verify_archived_source(plan, program_source_dir)
        content = (program_source_dir / f"{plan.source_html_sha256}.html").read_bytes()
        if verify_home_college(plan, content) != link.home_college:
            raise ValueError("Linked home college disagrees with program source")
    # Emit only after EVERY source and link succeeds. Matching hashes do not
    # prove the accuracy of a human-written paraphrase or personal applicability.
    return {
        "coverage": bundle.coverage,
        "verification": "archive_identity_paragraph_positions_and_exact_plan_links",
        "warnings": ["summary_semantics_need_review", "not_personal_applicability_or_eligibility",
            "selected_fragments_not_complete_policy", "university_and_college_rules_not_merged"],
        "policies": [{"policy_id": p.policy_id, "authority": p.authority,
            "source": p.source.model_dump(mode="json"), "coverage": p.coverage,
            "fragments": [{**f.model_dump(), "source_paragraph": blocks[p.policy_id][(f.source_kind, f.paragraph_index)][1]}
                for f in p.fragments]} for p in bundle.policies],
        "links": [link.model_dump(mode="json") for link in bundle.links],
    }


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-file", required=True, type=Path)
    parser.add_argument("--plan-file", required=True, type=Path, action="append")
    parser.add_argument("--policy-source-dir", required=True, type=Path)
    parser.add_argument("--program-source-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = audit_bundle(args.bundle_file, args.plan_file, args.policy_source_dir, args.program_source_dir)
    except (OSError, ValueError) as exc:
        print(f"Policy evidence audit failed ({type(exc).__name__}); no verified report emitted.", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
