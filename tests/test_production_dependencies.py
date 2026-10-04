"""Tests for production dependencies, lockfile consistency, and Dockerfile integrity (Batch 08C)."""

from __future__ import annotations

import importlib
from pathlib import Path
import re
import tomllib
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_lockfile_exists_and_contains_core_dependencies() -> None:
    lock_path = PROJECT_ROOT / "uv.lock"
    assert lock_path.exists(), "uv.lock must exist in repository root"

    lock_content = lock_path.read_text(encoding="utf-8")
    assert "version = 1" in lock_content or "[[package]]" in lock_content

    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)

    deps = pyproject.get("project", {}).get("dependencies", [])
    assert deps, "pyproject.toml must declare dependencies"

    # Extract base package names (e.g. 'uvicorn[standard]>=0.27' -> 'uvicorn')
    dep_names = []
    for dep in deps:
        name = re.split(r"[<>=~;!\[]", dep)[0].strip().lower()
        if name:
            dep_names.append(name)

    # Every declared dependency must appear as a package name in uv.lock
    for name in dep_names:
        # Check for name = "<name>" in uv.lock
        pattern = rf'name\s*=\s*"{re.escape(name)}"'
        assert re.search(pattern, lock_content, re.IGNORECASE) is not None, (
            f"Dependency {name!r} declared in pyproject.toml is missing from uv.lock"
        )


def test_wheel_packages_contain_all_internal_modules() -> None:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)

    wheel_packages = (
        pyproject.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("packages", [])
    )

    expected_packages = ["config", "db", "schemas", "scrapers", "llm", "rag", "api", "app"]
    for pkg in expected_packages:
        assert pkg in wheel_packages, f"Package {pkg!r} must be in hatchling wheel packages list"
        pkg_dir = PROJECT_ROOT / pkg
        assert pkg_dir.exists() and pkg_dir.is_dir(), f"Package directory {pkg_dir} must exist"


def test_dockerfile_production_pinning_and_exclusions() -> None:
    dockerfile_path = PROJECT_ROOT / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist"

    content = dockerfile_path.read_text(encoding="utf-8")

    # 1. uv sync must use --frozen
    assert "uv sync --frozen" in content, "Dockerfile uv sync must use --frozen for reproducible builds"

    # 2. Excludes should strip heavy training / scraping packages
    assert "--no-install-package torch" in content
    assert "--no-install-package pymupdf" in content

    # 3. ADR-0023: pyarrow must NOT be excluded as it is a hard streamlit requirement
    assert "--no-install-package pyarrow" not in content, (
        "pyarrow must NOT be excluded; streamlit dataframe_util requires it"
    )


def _out_of_lock_installs(content: str) -> str:
    """Every `uv pip install` command, with backslash continuations joined."""
    commands = re.findall(r"uv pip install(?:[^\n]*\\\n)*[^\n]*", content)
    assert commands, "Dockerfile must install the out-of-lock inference stack"
    return "\n".join(commands)


def test_out_of_lock_runtime_packages_are_pinned_exactly() -> None:
    """`uv sync --frozen` only covers uv.lock. CPU torch, optimum and
    optimum-intel are installed AFTER it, and every --build deploy re-runs
    those layers — a range there re-resolves on every deploy (the 2026-06-12
    crash-loop). They must be exact `==` pins to declared ARG versions."""
    content = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    pins = dict(re.findall(
        r"^ARG (TORCH_CPU_VERSION|OPTIMUM_VERSION|OPTIMUM_INTEL_VERSION)=(\S+)$",
        content, re.MULTILINE,
    ))
    assert set(pins) == {"TORCH_CPU_VERSION", "OPTIMUM_VERSION", "OPTIMUM_INTEL_VERSION"}
    for name, value in pins.items():
        assert re.fullmatch(r"\d+(\.\d+)+", value), f"{name} must be an exact version, got {value!r}"

    installs = _out_of_lock_installs(content)
    assert '"torch==${TORCH_CPU_VERSION}"' in installs
    assert '"optimum-intel[openvino]==${OPTIMUM_INTEL_VERSION}"' in installs
    assert '"optimum==${OPTIMUM_VERSION}"' in installs
    for loose in (">=", "<=", "~=", "!=", "<", ">"):
        assert loose not in installs, f"out-of-lock install uses a range ({loose!r})"


def test_build_records_the_resolved_out_of_lock_set() -> None:
    """The openvino extra's transitive packages still resolve at build time;
    the image must record what it actually got so the next pin is copied,
    not guessed."""
    content = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "uv pip freeze > /app/runtime-freeze.txt" in content


@pytest.mark.parametrize(
    "module_name",
    [
        "api.main",
        "config.settings",
        "db.connection",
        "db.repository",
        "rag.index",
        "rag.retriever",
        "schemas.course",
        "app.api_client",
    ],
)
def test_production_runtime_imports_smoke(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    assert mod is not None
