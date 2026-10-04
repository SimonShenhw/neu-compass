"""Tests for scripts/rehearse_recovery — disaster recovery rehearsal engine and CLI."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.rehearse_recovery import (
    _DeterministicEmbedder,
    create_fixture_backup,
    rehearse_recovery,
)


def test_rehearse_recovery_synthetic_fixture_success() -> None:
    report = rehearse_recovery(embedder=_DeterministicEmbedder(), cleanup=True)
    assert report["success"] is True
    assert report["sqlite_integrity"] == "ok"
    assert report["sqlite_fk_check"] == "ok"
    assert report["courses_count"] == 5
    assert report["faiss_status"] == "restored_from_backup"
    assert report["faiss_checksums_match"] is True
    assert report["search_verification"] is True
    assert "top_search_hit" in report
    assert not report["errors"]


def test_rehearse_recovery_force_rebuild_index() -> None:
    report = rehearse_recovery(
        force_rebuild_index=True,
        embedder=_DeterministicEmbedder(),
        cleanup=True,
    )
    assert report["success"] is True
    assert report["sqlite_integrity"] == "ok"
    assert report["faiss_status"] == "rebuilt_from_sqlite"
    assert report["faiss_count"] == 5
    assert report["faiss_checksums_match"] is True
    assert report["search_verification"] is True


def test_rehearse_recovery_corrupted_faiss_in_backup_fallbacks_to_rebuild(tmp_path: Path) -> None:
    backup_dir = tmp_path / "custom_backup"
    create_fixture_backup(backup_dir, embedder=_DeterministicEmbedder())

    # Corrupt faiss binary in backup
    (backup_dir / "faiss_index" / "index.faiss").write_bytes(b"invalid faiss binary")

    report = rehearse_recovery(
        backup_dir=backup_dir,
        embedder=_DeterministicEmbedder(),
        cleanup=True,
    )
    assert report["success"] is True
    assert report["faiss_status"] == "rebuilt_from_sqlite"
    assert report["faiss_checksums_match"] is True
    assert report["search_verification"] is True
    assert any("falling back to rebuild" in w for w in report["warnings"])


def test_rehearse_recovery_missing_sqlite_fails(tmp_path: Path) -> None:
    empty_backup = tmp_path / "empty_backup"
    empty_backup.mkdir()

    report = rehearse_recovery(backup_dir=empty_backup, cleanup=True)
    assert report["success"] is False
    assert any("Missing SQLite database" in err for err in report["errors"])


def test_rehearse_recovery_corrupted_sqlite_fails(tmp_path: Path) -> None:
    bad_backup = tmp_path / "bad_sqlite_backup"
    bad_backup.mkdir()
    (bad_backup / "courses.db").write_bytes(b"not a valid sqlite file")

    report = rehearse_recovery(backup_dir=bad_backup, cleanup=True)
    assert report["success"] is False
    assert any("integrity check failed" in err or "Unexpected exception" in err for err in report["errors"])


def test_rehearse_recovery_cli_subprocess() -> None:
    cmd = [
        sys.executable,
        "scripts/rehearse_recovery.py",
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"CLI rehearsal failed with stderr: {proc.stderr}"
    data = json.loads(proc.stdout)
    assert data["success"] is True
    assert data["sqlite_integrity"] == "ok"
    assert data["faiss_checksums_match"] is True
    assert data["search_verification"] is True
