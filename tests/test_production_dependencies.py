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

    expected_packages = ["config", "db", "schemas", "scrapers", "llm", "rag", "api"]  # R8 deleted app/.
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

    # 3. ADR-0023: pyarrow must NOT be excluded. Streamlit needed it at runtime; R8 deleted Streamlit, but
    #    ir-datasets (FlagEmbedding's) still depends on it and nobody checked the API never imports it.
    assert "--no-install-package pyarrow" not in content, (
        "pyarrow must NOT be excluded; see the Dockerfile's note (ADR-0023)"
    )


def _out_of_lock_install_commands(content: str) -> list[str]:
    """Every `uv pip install` command, backslash continuations included.
    Comment lines are dropped first (as Docker does): the comments mention
    `uv pip install` too, and they are not commands."""
    code = "\n".join(line for line in content.splitlines() if not line.lstrip().startswith("#"))
    commands = re.findall(r"uv pip install(?:[^\n]*\\\n)*[^\n]*", code)
    assert commands, "Dockerfile must install the out-of-lock inference stack"
    return commands


def _out_of_lock_installs(content: str) -> str:
    """Every `uv pip install` command, with backslash continuations joined."""
    return "\n".join(_out_of_lock_install_commands(content))


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


# What the out-of-lock layers resolve on their own: optimum-intel 2.0.0 leaves
# openvino/nncf/... unbounded, and torch 2.12 needs setuptools<82 (below the
# lock). Read off the 2026-10-04 production image's /app/runtime-freeze.txt.
OUT_OF_LOCK_TRANSITIVES = {
    "setuptools", "openvino", "openvino-tokenizers", "openvino-telemetry",
    "nncf", "ninja", "pydot", "pyparsing", "tabulate",
}


def test_out_of_lock_transitive_packages_are_constrained_exactly() -> None:
    """Exact top-level pins are not enough: their own dependencies floated
    too. The July and 2026-10-04 images got openvino 2026.2.1 vs 2026.4.1 from
    the same Dockerfile and live ranking shifted. Every out-of-lock install
    must read runtime-constraints.txt, and every entry there must be exact."""
    content = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    for command in _out_of_lock_install_commands(content):
        assert "--constraint runtime-constraints.txt" in command, (
            f"out-of-lock install does not read the constraints file: {command!r}"
        )

    pins: dict[str, str] = {}
    constraints = (PROJECT_ROOT / "runtime-constraints.txt").read_text(encoding="utf-8")
    for raw in constraints.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\d+(?:\.\d+)+)", line)
        assert match, f"runtime-constraints.txt entries must be exact name==version pins: {line!r}"
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        assert name not in pins, f"{name} is pinned twice"
        pins[name] = match.group(2)

    missing = OUT_OF_LOCK_TRANSITIVES - set(pins)
    assert not missing, f"floating out-of-lock packages without a pin: {sorted(missing)}"


def test_build_records_the_resolved_out_of_lock_set() -> None:
    """The image must record the full set it actually resolved: that freeze
    is what runtime-constraints.txt is copied from, so a re-pin copies it
    instead of guessing."""
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
    ],
)
def test_production_runtime_imports_smoke(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_nothing_imports_the_deleted_streamlit_ui_and_the_dependency_is_gone() -> None:
    """R8 deleted the Streamlit UI (app/) and its dependency; R0 had kept the API off app/ so that it could.
    中文：R8 删了 Streamlit 界面（app/）和这个依赖；R0 起 API 就不导入 app/，就是为了能删。"""
    import ast

    dirs = ("api", "config", "db", "eval", "llm", "rag", "schemas", "scrapers", "scripts", "tests")
    paths = [path for name in dirs for path in (PROJECT_ROOT / name).rglob("*.py") if "__pycache__" not in path.parts]
    assert len(paths) > 100
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            names = ([node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else
                     [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                assert name.split(".")[0] not in {"app", "streamlit"}, f"{path.relative_to(PROJECT_ROOT)} imports {name}"
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any(re.match(r"streamlit\b", dep, re.I) for dep in pyproject["project"]["dependencies"])
    assert "app" not in pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert 'name = "streamlit"' not in (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    for name in ("Dockerfile", "docker-compose.yml"):  # Streamlit's port. 中文：Streamlit 的端口。
        assert "8501" not in (PROJECT_ROOT / name).read_text(encoding="utf-8"), name
