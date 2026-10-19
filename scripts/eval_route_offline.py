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


def _one_line(exc):
    return " ".join(str(exc).split())[:200]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], allow_abbrev=False)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists() or not args.out.parent.is_dir() or args.out.resolve().is_relative_to(ROOT):
        print("setup error: --out must be a new file in an existing directory", file=sys.stderr)
        return 2
    from eval.route_guard import OfflineViolation

    try:
        from eval.route_eval import exit_code, run_eval

        report = run_eval()
        with args.out.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError) as exc:
        print(f"offline evaluation error: {type(exc).__name__}: {_one_line(exc)}", file=sys.stderr)
        return 2
    except OfflineViolation as exc:
        # Isolation is exit 1 wherever it trips, also before a report exists. 中文：隔离触发一律退出 1，没有报告时也一样。
        print(f"offline evaluation isolation violation: {_one_line(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - any other harness failure means the run is incomplete, not "checks failed"
        print(f"offline evaluation incomplete: {type(exc).__name__}: {_one_line(exc)}", file=sys.stderr)
        return 3
    print(json.dumps({"status": report["status"], "evidence_layer": report["evidence_layer"],
                      "population": report["population"], "production_quality_verified": False,
                      "route_pass": report["route_contract"]["pass"], "route_fail": report["route_contract"]["fail"],
                      "stream_fail": report["stream_contract"]["fail"], "expectation_mismatches": report["expectation_mismatches"],
                      "isolation": report["isolation"], "accounting_errors": report["database"]["accounting_errors"]},
                     ensure_ascii=False))
    # Deliberately bad scripted answers are negative controls, not a failed harness run.
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
