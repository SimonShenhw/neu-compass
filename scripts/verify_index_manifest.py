"""Verify FAISS index files and index_manifest.json checksums.

Checks:
  1. Required index files exist (index.faiss, id_map.json)
  2. Manifest file exists and conforms to schema
  3. SHA-256 checksums of index.faiss and id_map.json match manifest
  4. (Optional) Embedding model matches --expected-model
  5. (Optional) Verify loading the index into FAISS memory

Usage:
    python scripts/verify_index_manifest.py
    python scripts/verify_index_manifest.py --index-path /path/to/idx
    python scripts/verify_index_manifest.py --expected-model BAAI/bge-m3 --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rag.index import FaissIndex  # noqa: E402


def verify_index(
    index_path: str | Path,
    *,
    expected_model: str | None = None,
    verify_load: bool = False,
) -> dict[str, Any]:
    """Verify integrity and manifest metadata of a FAISS index directory."""
    target_path = Path(index_path)
    result: dict[str, Any] = {
        "index_path": str(target_path),
        "valid": False,
        "has_manifest": False,
        "manifest": None,
        "checksums_match": False,
        "model_match": None,
        "errors": [],
        "warnings": [],
    }

    if not target_path.exists() or not target_path.is_dir():
        result["errors"].append(f"Index directory does not exist: {target_path}")
        return result

    integrity = FaissIndex.verify_integrity(target_path)
    result["has_manifest"] = integrity.get("has_manifest", False)
    result["manifest"] = integrity.get("manifest")

    if not integrity.get("valid", False):
        if integrity.get("error") == "missing_required_files":
            missing = integrity.get("missing", [])
            result["errors"].append(f"Missing required index files: {', '.join(missing)}")
        elif "corrupted_manifest" in str(integrity.get("error")):
            result["errors"].append(f"Corrupted index_manifest.json: {integrity.get('error')}")
        else:
            result["errors"].append("Checksums do not match manifest or files are corrupt")
            if not integrity.get("index_sha256_match", True):
                result["errors"].append("index.faiss SHA-256 does not match manifest")
            if not integrity.get("id_map_sha256_match", True):
                result["errors"].append("id_map.json SHA-256 does not match manifest")
        return result

    if not result["has_manifest"]:
        result["warnings"].append("Legacy index without index_manifest.json metadata")
        result["valid"] = True
        return result

    result["checksums_match"] = integrity.get("checksums_match", False)

    # Check expected embedding model
    if expected_model is not None:
        manifest_model = result["manifest"].get("embedding_model") if result["manifest"] else None
        if manifest_model != expected_model:
            result["model_match"] = False
            result["errors"].append(
                f"Embedding model mismatch: expected {expected_model!r}, got {manifest_model!r}"
            )
            return result
        result["model_match"] = True

    # Optionally load into memory to test faiss deserialization
    if verify_load:
        try:
            loaded = FaissIndex.load(target_path, verify_checksums=True)
            result["loaded_count"] = loaded.count
            result["loaded_dim"] = loaded.dim
        except Exception as exc:
            result["errors"].append(f"Failed to load FAISS index into memory: {exc}")
            return result

    result["valid"] = True
    return result


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-path", default=None, help="Override settings.faiss_index_path")
    parser.add_argument("--expected-model", default=None, help="Expected embedding model identifier")
    parser.add_argument("--verify-load", action="store_true", help="Also load index into memory to verify binary compatibility")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    if args.index_path is None:
        from config import settings  # noqa: PLC0415
        index_path = settings.faiss_index_path
    else:
        index_path = args.index_path

    report = verify_index(
        index_path=index_path,
        expected_model=args.expected_model,
        verify_load=args.verify_load,
    )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["valid"] else 1

    print(f"=> Verifying FAISS index at: {report['index_path']}")
    if report["valid"]:
        print("   Status: VALID [OK]")
        if report["has_manifest"]:
            m = report["manifest"]
            print(f"   Manifest version : {m.get('manifest_version')}")
            print(f"   Embedding model  : {m.get('embedding_model')}")
            print(f"   Vector count     : {m.get('count')}")
            print(f"   Dimension        : {m.get('dimension')}")
            print(f"   Created at       : {m.get('created_at')}")
            print("   Checksums        : MATCHED [OK]")
        else:
            print("   Manifest         : NONE (Legacy index)")
        if report["warnings"]:
            for w in report["warnings"]:
                print(f"   WARNING: {w}")
        return 0
    else:
        print("   Status: INVALID [FAILED]")
        for err in report["errors"]:
            print(f"   ERROR: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(cli())
