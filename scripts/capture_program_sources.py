"""Capture official inputs to an explicit archive directory, never to a DB.

Generated immutable input files are private data/raw artifacts, not curated rules.
中文：固定来源输入与摘要；不把网页自动解析成已核验规则，不覆盖同名文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schemas.program_plan import ProgramPlan  # noqa: E402
from schemas.program_source import MAX_HTML_BYTES, SourceCapture, inspect_html  # noqa: E402


def capture_sources(plan_file: Path, output_dir: Path, *, client: httpx.Client | None = None) -> list[dict]:
    payload = json.loads(plan_file.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Expected a nonempty plan array")
    plans = [ProgramPlan.model_validate(item) for item in payload]
    unique = {}
    for plan in plans:
        prior = unique.get(plan.source_url)
        if prior and (prior.source_catalog_year, prior.source_title) != (plan.source_catalog_year, plan.source_title):
            raise ValueError("One URL cannot represent inconsistent declared inputs")
        unique[plan.source_url] = plan
    owned_client = client is None
    if owned_client:
        client = httpx.Client(timeout=30, follow_redirects=False)
    results = []
    try:
        for url, plan in unique.items():
            chunks, size = [], 0
            with client.stream("GET", url, follow_redirects=False) as response:
                response.raise_for_status()
                if response.url != httpx.URL(url) or response.headers.get("content-type", "").split(";", 1)[0].lower().strip() != "text/html":
                    raise ValueError("Only the exact official HTML response is accepted")
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_HTML_BYTES:
                        raise ValueError("HTML exceeds capture budget")
                    chunks.append(chunk)
            content = b"".join(chunks)
            title = inspect_html(content, plan)
            digest = hashlib.sha256(content).hexdigest()
            metadata = SourceCapture(url=url, catalog_year=plan.source_catalog_year,
                captured_at=datetime.now(timezone.utc), sha256=digest, byte_count=len(content), page_title=title)
            output_dir.mkdir(parents=True, exist_ok=True)
            html_path, metadata_path = output_dir / f"{digest}.html", output_dir / f"{digest}.json"
            if html_path.exists():
                if html_path.stat().st_size > MAX_HTML_BYTES or html_path.read_bytes() != content:
                    raise ValueError("Archive filename collision; existing input preserved")
            else:
                with html_path.open("xb") as file:
                    file.write(content)
            if metadata_path.exists():
                if metadata_path.stat().st_size > 16_000:
                    raise ValueError("Existing archive metadata too large")
                old = SourceCapture.model_validate_json(metadata_path.read_text(encoding="utf-8"))
                if (old.url, old.catalog_year, old.sha256, old.byte_count, old.page_title) != (url, metadata.catalog_year, digest, len(content), title):
                    raise ValueError("Existing metadata conflict; preserved")
                metadata = old  # Reuse the actual original timestamp, not today's date.
            else:
                with metadata_path.open("x", encoding="utf-8") as file:
                    file.write(metadata.model_dump_json(indent=2) + "\n")
            results.append(metadata.model_dump(mode="json"))
        return results
    finally:
        if owned_client:
            client.close()


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(capture_sources(args.plan_file, args.output_dir), ensure_ascii=False, indent=2))
    except (OSError, ValueError, httpx.HTTPError) as exc:
        print(f"Source capture failed ({type(exc).__name__}); any prior immutable inputs remain preserved.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
