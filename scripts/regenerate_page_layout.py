"""Reproduce offline AppTest layout fixtures; checking is the default (no HEAD assumption).

Workflow: BEFORE a product change, run this script without arguments and confirm
all committed fixtures match. For intentional layout changes, freeze expectations
on the agreed reference tree, then use --write and review every fixture diff.
Never bless a regression merely because --write makes a failing test pass.
Fixtures encode relative chat/detail paths, complete node and delta protos,
canonical integral floats, stable widget keys, and omit script-generated form IDs.
Uses only synthetic data/MockTransport, not a live API, model, account or database.

Usage: python -B scripts/regenerate_page_layout.py [--write]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.page_layout_support import (  # noqa: E402
    SNAPSHOT_NAMES,
    SNAPSHOTS,
    install_backend,
    layout_snapshot,
    render_layout_case,
    snapshot_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="explicitly update reference fixtures")
    args = parser.parse_args()
    mismatches = []
    if args.write:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    for name in SNAPSHOT_NAMES:
        with pytest.MonkeyPatch.context() as patch:
            backend = install_backend(patch)
            app, messages = render_layout_case(name, patch, backend)
            text = snapshot_json(layout_snapshot(app, messages))
        path = SNAPSHOTS / f"{name}.json"
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.exists() or path.read_text(encoding="utf-8") != text:
            mismatches.append(name)
        print(f"{name}: {'written' if args.write else 'DIFF' if name in mismatches else 'match'}", flush=True)
    if mismatches:
        print(f"STOP: reference fixtures differ: {mismatches}", file=sys.stderr)
    return int(bool(mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
