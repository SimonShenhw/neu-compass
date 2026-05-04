"""Full sweep of NEU course catalog → JSONL files under raw_data/neu_catalog/.

Run:
    uv run python scripts/scrape_neu_catalog.py                  # all depts (~190)
    uv run python scripts/scrape_neu_catalog.py --dept aai       # single dept
    uv run python scripts/scrape_neu_catalog.py --limit 5        # first 5 depts (smoke)
    uv run python scripts/scrape_neu_catalog.py --out /tmp/cat   # custom output dir
    uv run python scripts/scrape_neu_catalog.py --overwrite      # re-fetch existing

Defaults:
  - Output dir: <sqlite_path's parent>/raw/neu_catalog/  (per ADR-0014, runtime
    data lives in WSL home, so by default this is ~/neu-compass-data/raw/neu_catalog/)
  - 1.0 second between dept requests (polite to NEU's servers)
  - Resumable: depts whose .jsonl already exists are skipped unless --overwrite

JSONL schema: one CatalogEntry per line (Pydantic .model_dump_json()). Loadable
via scripts/ingest_neu_catalog.py to populate the courses table.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings  # noqa: E402
from scrapers._base import create_client  # noqa: E402
from scrapers.neu_catalog import fetch_dept, list_dept_slugs  # noqa: E402

DEFAULT_OUT_DIR = Path(settings.sqlite_path).resolve().parent / "raw" / "neu_catalog"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dept", help="Single dept slug, e.g. 'aai'. Default: all depts.")
    p.add_argument("--limit", type=int, help="Max depts to process (smoke).")
    p.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR,
        help=f"Output dir. Default: {DEFAULT_OUT_DIR}",
    )
    p.add_argument(
        "--overwrite", action="store_true",
        help="Re-fetch depts that already have JSONL on disk.",
    )
    p.add_argument(
        "--rate-limit-sec", type=float, default=1.0,
        help="Sleep between dept requests (default: 1.0).",
    )
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"=> output dir: {args.out}")

    with create_client() as client:
        if args.dept:
            slugs = [args.dept.lower().strip("/")]
        else:
            print("=> fetching dept index ...")
            slugs = list_dept_slugs(client=client)
        print(f"=> {len(slugs)} dept(s) to process")

        if args.limit is not None:
            slugs = slugs[: args.limit]
            print(f"   (limited to first {len(slugs)})")

        total_courses = 0
        for i, slug in enumerate(slugs, 1):
            out_path = args.out / f"{slug}.jsonl"
            if out_path.exists() and not args.overwrite:
                print(f"  [{i}/{len(slugs)}] {slug}: skip (exists, use --overwrite to refresh)")
                continue
            try:
                entries = fetch_dept(slug, client=client)
            except Exception as e:
                print(f"  [{i}/{len(slugs)}] {slug}: ERROR {e!r}")
                continue
            with out_path.open("w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(entry.model_dump_json() + "\n")
            total_courses += len(entries)
            print(f"  [{i}/{len(slugs)}] {slug}: {len(entries):>3} courses → {out_path.name}")

            if i < len(slugs):
                time.sleep(args.rate_limit_sec)

    print(f"=> done. {total_courses} courses across {len(slugs)} dept(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
