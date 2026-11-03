"""The repository's curated program plans (data/program_plan_seed), as the tests read them. Moved here from
tests/test_program_plan_links.py when R8 deleted that file's Streamlit tests.
中文：仓库里策展的培养方案，测试按这个读。R8 删 test_program_plan_links.py 的 Streamlit 测试时搬来。
"""

import json
from pathlib import Path

from schemas.program_plan import ProgramPlan

ROOT = Path(__file__).resolve().parent.parent


def plans():
    return [ProgramPlan.model_validate(p)
        for name in ['boston_2026_2027_extended_rules.json', 'boston_2026_2027_pathway_rules.json']
        for p in json.loads((ROOT / 'data/program_plan_seed' / name).read_text())]
