"""Explicit official department captures; no DB, no derived eligibility.

中文：只固定来源输入；同名原文/元数据不覆盖，重复抓取保留原时间。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from schemas.course_requisite_source import CourseRequisiteSource, MAX_BYTES, inspect_course_html  # noqa: E402


def capture_departments(departments: list[str], catalog_year: str, output_dir: Path, *, client=None) -> list[dict]:
    if not departments or len(departments) > 20 or any(not re.fullmatch(r"[a-z]{2,8}", dept) for dept in departments):
        raise ValueError("Explicit bounded lowercase department list required")
    if not re.fullmatch(r"\d{4}-\d{4}", catalog_year) or int(catalog_year[5:]) != int(catalog_year[:4]) + 1:
        raise ValueError("Explicit consecutive edition required")
    owned = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False)
    results = []
    try:
        for dept in dict.fromkeys(departments):
            url = f"https://catalog.northeastern.edu/course-descriptions/{dept}/"
            chunks, size = [], 0
            with client.stream("GET", url, follow_redirects=False) as response:
                response.raise_for_status()
                if response.url != httpx.URL(url) or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/html":
                    raise ValueError("Exact official HTML response required")
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Capture exceeds size budget")
                    chunks.append(chunk)
            content = b"".join(chunks)
            title = inspect_course_html(content, url=url, catalog_year=catalog_year)
            metadata = CourseRequisiteSource(url=url, catalog_year=catalog_year,
                captured_at=datetime.now(timezone.utc), sha256=hashlib.sha256(content).hexdigest(), byte_count=len(content), page_title=title)
            output_dir.mkdir(parents=True, exist_ok=True)
            stem = output_dir / metadata.sha256
            html, sidecar = stem.with_suffix(".html"), stem.with_suffix(".json")
            if html.exists():
                if html.stat().st_size > MAX_BYTES or html.read_bytes() != content:
                    raise ValueError("Existing archive collision; preserved")
            else:
                with html.open("xb") as file:
                    file.write(content)
            if sidecar.exists():
                if sidecar.stat().st_size > 16_000:
                    raise ValueError("Existing metadata exceeds budget")
                old = CourseRequisiteSource.model_validate_json(sidecar.read_text(encoding="utf-8"))
                if old.model_dump(exclude={"captured_at"}) != metadata.model_dump(exclude={"captured_at"}):
                    raise ValueError("Existing metadata conflict; preserved")
                metadata = old
            else:
                with sidecar.open("x", encoding="utf-8") as file:
                    file.write(metadata.model_dump_json(indent=2) + "\n")
            results.append(metadata.model_dump(mode="json"))
        return results
    finally:
        if owned:
            client.close()


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dept", required=True, action="append")
    parser.add_argument("--catalog-year", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(capture_departments(args.dept, args.catalog_year, args.output_dir), ensure_ascii=False, indent=2))
    except (OSError, ValueError, httpx.HTTPError) as exc:
        print(f"Course source capture failed ({type(exc).__name__}); prior immutable inputs preserved.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
