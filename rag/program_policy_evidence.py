"""File-backed selected policy evidence, not used by retrieval or the LLM.

No fetching, caching, DB connection, migration or writes. Missing private
archives are an explicit unavailable state, never a reason to guess policy.
中文：每次只读核对选定方案，失败不回退旧 seed，不输出部分可信片段。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from db.program_plan_repository import content_hash
from schemas.program_plan import ProgramPlan
from schemas.program_policy import ProgramPolicyBundle, verify_home_college, verify_policy_source
from schemas.program_policy_view import PolicyScope, ProgramPolicyView
from schemas.program_source import MAX_HTML_BYTES, verify_archived_source

BASE_WARNINGS = ["selected_fragments_not_complete_policy", "not_personal_applicability_or_eligibility",
    "university_and_college_rules_not_merged", "archive_check_not_source_authenticity_or_summary_semantics"]


class ProgramPolicyReader:
    def __init__(self, bundle_file: Path, policy_source_dir: Path, program_source_dir: Path):
        self.bundle_file = Path(bundle_file)
        self.policy_source_dir = Path(policy_source_dir)
        self.program_source_dir = Path(program_source_dir)

    def read(self, plan: ProgramPlan) -> ProgramPolicyView:
        plan = ProgramPlan.model_validate(plan.model_dump())
        base = dict(plan_id=plan.plan_id, scope=PolicyScope.from_plan(plan), plan_content_sha256=content_hash(plan))
        def failure(status, warning):
            return ProgramPolicyView(**base, status=status, warnings=[*BASE_WARNINGS, warning])
        if plan.review_status != "source_checked":
            return failure("draft", "policy_plan_not_source_checked")
        try:
            # Limit reads as well as stat: never turn an oversized file into a
            # silently truncated valid bundle or an unbounded runtime read.
            with self.bundle_file.open("rb") as file:
                data = file.read(300_001)
            if len(data) > 300_000:
                raise ValueError("Policy bundle outside size budget")
            bundle = ProgramPolicyBundle.model_validate_json(data.decode("utf-8-sig"))
        except FileNotFoundError:
            return failure("unavailable", "policy_bundle_missing")
        except OSError:
            return failure("unavailable", "policy_bundle_unreadable")
        except ValueError:
            return failure("unusable", "policy_bundle_invalid")
        link = next((item for item in bundle.links if item.plan_id == plan.plan_id), None)
        if link is None:
            return failure("not_linked", "no_policy_link_for_exact_plan")
        if (link.scope_key() != plan.scope_key() or link.plan_content_sha256 != base["plan_content_sha256"]
                or bundle.checked_on < plan.checked_on):
            return failure("stale", "policy_plan_scope_or_revision_changed")
        try:
            verify_archived_source(plan, self.program_source_dir)
            with (self.program_source_dir / f"{plan.source_html_sha256}.html").open("rb") as file:
                program_html = file.read(MAX_HTML_BYTES + 1)
            # A second read used for association cannot silently switch to bytes
            # changed after verification. This is not an atomic filesystem claim.
            if len(program_html) > MAX_HTML_BYTES or hashlib.sha256(program_html).hexdigest() != plan.source_html_sha256:
                raise ValueError("Program archive changed during read")
            if verify_home_college(plan, program_html) != link.home_college:
                raise ValueError("Home college/source mismatch")
            by_id = {p.policy_id: p for p in bundle.policies}
            policies = []
            for policy_id in link.policy_ids:
                policy = by_id[policy_id]
                blocks = verify_policy_source(policy, self.policy_source_dir)
                evidence = policy.model_dump(mode="json")
                evidence["fragments"] = [{**f.model_dump(mode="json"),
                    "source_paragraph": blocks[(f.source_kind, f.paragraph_index)][1]} for f in policy.fragments]
                policies.append(evidence)
            return ProgramPolicyView(**base, status="ready", link=link, policies=policies,
                checked_by=bundle.checked_by, checked_on=bundle.checked_on, warnings=BASE_WARNINGS.copy())
        except FileNotFoundError:
            return failure("unavailable", "policy_or_program_archive_missing")
        except OSError:
            return failure("unavailable", "policy_or_program_archive_unreadable")
        except ValueError:
            return failure("unusable", "policy_or_program_archive_invalid")
