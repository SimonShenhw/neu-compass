"""Tests for scripts/verify_index_manifest — CLI and API."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from rag.embedder import EMBEDDING_DIM, _l2_normalize
from rag.index import FaissIndex
from scripts.verify_index_manifest import verify_index


def _vec(seed: int, dim: int = EMBEDDING_DIM) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim, dtype=np.float32).reshape(1, -1)
    return _l2_normalize(v)


def test_verify_clean_index_with_manifest(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["course-1"])
    idx.save(tmp_path, model_name="BAAI/bge-m3")

    report = verify_index(tmp_path, expected_model="BAAI/bge-m3", verify_load=True)
    assert report["valid"] is True
    assert report["has_manifest"] is True
    assert report["checksums_match"] is True
    assert report["model_match"] is True
    assert report["loaded_count"] == 1
    assert report["loaded_dim"] == EMBEDDING_DIM
    assert not report["errors"]


def test_verify_model_mismatch(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["course-1"])
    idx.save(tmp_path, model_name="BAAI/bge-m3")

    report = verify_index(tmp_path, expected_model="other/model")
    assert report["valid"] is False
    assert report["model_match"] is False
    assert any("Embedding model mismatch" in err for err in report["errors"])


def test_verify_nonexistent_directory(tmp_path: Path) -> None:
    non_existent = tmp_path / "not_found"
    report = verify_index(non_existent)
    assert report["valid"] is False
    assert any("does not exist" in err for err in report["errors"])


def test_verify_missing_required_files(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    (tmp_path / FaissIndex.INDEX_FILE).unlink()
    report = verify_index(tmp_path)
    assert report["valid"] is False
    assert any("Missing required index files" in err for err in report["errors"])


def test_verify_checksum_mismatch(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    # Tamper with index.faiss
    (tmp_path / FaissIndex.INDEX_FILE).write_bytes(b"tampered binary")
    report = verify_index(tmp_path)
    assert report["valid"] is False
    assert any("index.faiss SHA-256 does not match" in err for err in report["errors"])


def test_verify_legacy_without_manifest(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path)

    (tmp_path / FaissIndex.MANIFEST_FILE).unlink()
    report = verify_index(tmp_path)
    assert report["valid"] is True
    assert report["has_manifest"] is False
    assert any("Legacy index" in w for w in report["warnings"])


def test_verify_cli_subprocess(tmp_path: Path) -> None:
    idx = FaissIndex()
    idx.add(_vec(1), ["c1"])
    idx.save(tmp_path, model_name="BAAI/bge-m3")

    # Run CLI with --json
    cmd = [
        sys.executable,
        "scripts/verify_index_manifest.py",
        "--index-path",
        str(tmp_path),
        "--expected-model",
        "BAAI/bge-m3",
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["valid"] is True
    assert data["has_manifest"] is True
    assert data["checksums_match"] is True

    # Run CLI with mismatch -> exit code 1
    cmd_bad = [
        sys.executable,
        "scripts/verify_index_manifest.py",
        "--index-path",
        str(tmp_path),
        "--expected-model",
        "wrong-model",
    ]
    proc_bad = subprocess.run(cmd_bad, capture_output=True, text=True, check=False)
    assert proc_bad.returncode == 1
