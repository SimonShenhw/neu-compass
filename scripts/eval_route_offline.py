"""Run the fixed synthetic /chat suite to a NEW --out JSON file. No real API/model/DB options.

中文：固定离线合成评测；只有 --out，新文件独占创建；结果不是生产质量证明。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], allow_abbrev=False)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists() or not args.out.parent.is_dir():
        print("setup error: --out must be a new file in an existing directory", file=sys.stderr)
        return 2
    try:
        from eval.route_eval import run_eval

        report = run_eval()
        with args.out.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError) as exc:
        print(f"offline evaluation error: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "evidence_layer": report["evidence_layer"],
                      "population": report["population"], "production_quality_verified": False}))
    # Deliberately bad scripted answers are negative controls, not a failed harness run.
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
