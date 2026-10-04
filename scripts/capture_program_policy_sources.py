"""Capture explicit policy chapters to immutable private inputs; no rules/DB writes."""

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

from schemas.program_policy import PolicySourceRequest, inspect_policy_html  # noqa: E402
from schemas.program_source import MAX_HTML_BYTES, SourceCapture  # noqa: E402


def capture_policy_sources(request_file: Path, output_dir: Path, *, client: httpx.Client | None = None) -> list[dict]:
    if request_file.stat().st_size > 100_000:
        raise ValueError("Policy requests outside size budget")
    payload = json.loads(request_file.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list) or not 1 <= len(payload) <= 30:
        raise ValueError("Expected 1-30 explicit policy source requests")
    requests = [PolicySourceRequest.model_validate(item) for item in payload]
    unique = {}
    for request in requests:
        if request.url in unique and unique[request.url] != request:
            raise ValueError("One URL cannot represent conflicting policy identities")
        unique[request.url] = request
    owned = client is None
    if owned:
        client = httpx.Client(timeout=30, follow_redirects=False)
    results = []
    try:
        for url, request in unique.items():
            chunks, size = [], 0
            with client.stream("GET", url, follow_redirects=False) as response:
                response.raise_for_status()
                if response.url != httpx.URL(url) or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/html":
                    raise ValueError("Only the exact official HTML response is accepted")
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_HTML_BYTES:
                        raise ValueError("Policy HTML exceeds capture budget")
                    chunks.append(chunk)
            content = b"".join(chunks)
            inspect_policy_html(content, request)
            digest = hashlib.sha256(content).hexdigest()
            metadata = SourceCapture(url=url, catalog_year=request.catalog_year, captured_at=datetime.now(timezone.utc),
                sha256=digest, byte_count=len(content), page_title=request.page_title)
            output_dir.mkdir(parents=True, exist_ok=True)
            html_path, sidecar = output_dir / f"{digest}.html", output_dir / f"{digest}.json"
            # Check BOTH existing artifacts before adding either missing half.
            # 中文：冲突时保留已有输入；重复抓取保留首次时间。
            if html_path.exists() and (html_path.stat().st_size > MAX_HTML_BYTES or html_path.read_bytes() != content):
                raise ValueError("Existing policy HTML conflict; preserved")
            if sidecar.exists():
                if sidecar.stat().st_size > 16_000:
                    raise ValueError("Existing policy metadata too large")
                old = SourceCapture.model_validate_json(sidecar.read_text(encoding="utf-8"))
                if old.model_dump(exclude={"captured_at"}) != metadata.model_dump(exclude={"captured_at"}):
                    raise ValueError("Existing policy metadata conflict; preserved")
                metadata = old
            if not html_path.exists():
                with html_path.open("xb") as file:
                    file.write(content)
            if not sidecar.exists():
                with sidecar.open("x", encoding="utf-8") as file:
                    file.write(metadata.model_dump_json(indent=2) + "\n")
            results.append(metadata.model_dump(mode="json"))
        return results
    finally:
        if owned:
            client.close()


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = capture_policy_sources(args.request_file, args.output_dir)
    except (OSError, ValueError, httpx.HTTPError) as exc:
        print(f"Policy capture failed ({type(exc).__name__}); prior inputs preserved.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
