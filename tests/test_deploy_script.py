"""Offline deployment acceptance tests; every external operation is mocked.

Runs with PowerShell on Windows/Linux, or Windows PowerShell via WSL interop.
No SSH connection, Docker command, HTTP request, or file transfer is made.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POWERSHELL = next(
    (path for name in ("pwsh", "pwsh.exe", "powershell.exe") if (path := shutil.which(name))),
    None,
)
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not installed")

MOCK_RUNNER = r"""
$global:reviewScenario = '__SCENARIO__'
$global:reviewProbeCount = 0
$global:reviewNow = [datetime]'2026-09-30T12:00:00'
function tailscale.exe { $global:LASTEXITCODE = 0 }
function wsl { throw 'Unexpected WSL operation in offline test' }
function scp { throw 'Unexpected file transfer in offline test' }
function ssh {
    $command = $args[-1]
    $global:LASTEXITCODE = 0
    if ($command -match 'docker compose up') {
        Write-Host "REVIEW_COMPOSE: $command"
        if ($global:reviewScenario -eq 'compose_failure') {
            # Reproduce the old remote pipeline: tail would mask compose's exit.
            $global:LASTEXITCODE = if ($command -match '\|') { 0 } else { 23 }
        }
        return
    }
    if ($command -match 'echo ok') { return 'ok' }
    throw "Unexpected SSH command in offline test: $command"
}
function Get-Date {
    $global:reviewNow = $global:reviewNow.AddSeconds(1)
    return $global:reviewNow
}
function Start-Sleep { param([int]$Seconds) }
function Invoke-WebRequest {
    param([string]$Uri, [int]$TimeoutSec, [switch]$UseBasicParsing, [string]$ErrorAction)
    Write-Host "REVIEW_PROBE: $Uri"
    if ($Uri -like '*/ready') {
        $global:reviewProbeCount++
        if ($global:reviewScenario -eq 'network_failure') { throw 'Simulated network failure' }
        if ($global:reviewScenario -eq 'transient' -and $global:reviewProbeCount -eq 1) {
            throw 'Simulated HTTP 503'
        }
        $httpStatus = if ($global:reviewScenario -eq 'api_unavailable') { 503 } else { 200 }
        $body = switch ($global:reviewScenario) {
            'warming' { '{"status":"warming","courses_indexed":3,"bm25_corpus":3}' }
            'empty_index' { '{"status":"ready","courses_indexed":0,"bm25_corpus":3}' }
            'empty_bm25' { '{"status":"ready","courses_indexed":3,"bm25_corpus":0}' }
            'invalid_json' { 'not-json' }
            default { '{"status":"ready","courses_indexed":3,"bm25_corpus":3}' }
        }
        return [pscustomobject]@{StatusCode=$httpStatus; Content=$body}
    }
    if ($Uri -like '*/_stcore/health') {
        $body = if ($global:reviewScenario -eq 'ui_unhealthy') { '<html>proxy error</html>' } else { 'ok' }
        return [pscustomobject]@{StatusCode=200; Content=$body}
    }
    if ($Uri -like '*/resolve/course?ref=CS-5800') {
        $httpStatus = if ($global:reviewScenario -eq 'resolver_missing') { 404 } else { 200 }
        $body = if ($global:reviewScenario -eq 'resolver_empty') {
            '{"ref":"CS-5800","matches":[]}'
        } else {
            '{"ref":"CS-5800","matches":[{"course_id":"neu-cs-5800","primary_code":"CS 5800","primary_name":"Algorithms"}]}'
        }
        return [pscustomobject]@{StatusCode=$httpStatus; Content=$body}
    }
    if ($Uri -like '*/coop') {
        $httpStatus = if ($global:reviewScenario -eq 'coop_unavailable') { 503 } else { 200 }
        $body = switch ($global:reviewScenario) {
            'coop_invalid_json' { '[broken' }
            'coop_wrong_shape' { '{}' }
            default { '[]' }
        }
        # Lower-case name on purpose (ASGI sends lower-case header names).
        $moderation = if ($global:reviewScenario -eq 'coop_unmigrated') { 'missing' } else { 'available' }
        $headers = if ($global:reviewScenario -eq 'coop_no_header') { @{} } else { @{'x-coop-moderation' = $moderation} }
        return [pscustomobject]@{StatusCode=$httpStatus; Content=$body; Headers=$headers}
    }
    throw "Unexpected HTTP operation in offline test: $Uri"
}
try {
    & '__DEPLOY_SCRIPT__' -SkipCode -NoBuild -Force -NasHost review-only.invalid -ReadyTimeoutSeconds 5
} catch {
    Write-Error $_
    exit 1
}
exit $LASTEXITCODE
"""


def _run_deploy(scenario: str) -> subprocess.CompletedProcess[str]:
    script_path = str(PROJECT_ROOT / "scripts" / "deploy.ps1")
    if sys.platform != "win32" and POWERSHELL and POWERSHELL.lower().endswith(".exe"):
        script_path = subprocess.run(
            ["wslpath", "-w", script_path], check=True, capture_output=True, text=True,
        ).stdout.strip()
    source = MOCK_RUNNER.replace("__SCENARIO__", scenario).replace(
        "__DEPLOY_SCRIPT__", script_path.replace("'", "''"),
    )
    encoded = base64.b64encode(source.encode("utf-16-le")).decode("ascii")
    assert POWERSHELL is not None
    # Process-only policy override for our local fixture; never changes host policy.
    return subprocess.run(
        [
            POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-OutputFormat", "Text", "-EncodedCommand", encoded,
        ],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30, check=False,
    )


@pytest.mark.parametrize("scenario", ["success", "transient"])
def test_deploy_requires_all_readonly_acceptance_probes(scenario: str) -> None:
    result = _run_deploy(scenario)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Deploy done" in result.stdout
    assert "REVIEW_PROBE: http://review-only.invalid:8000/ready" in result.stdout
    assert "REVIEW_PROBE: http://review-only.invalid:8501/_stcore/health" in result.stdout
    assert "REVIEW_PROBE: http://review-only.invalid:8000/resolve/course?ref=CS-5800" in result.stdout
    assert "REVIEW_PROBE: http://review-only.invalid:8000/coop" in result.stdout
    if scenario == "transient":
        assert result.stdout.count("REVIEW_PROBE: http://review-only.invalid:8000/ready") >= 2


@pytest.mark.parametrize(
    "scenario",
    [
        "compose_failure", "warming", "empty_index", "empty_bm25", "invalid_json",
        "api_unavailable", "network_failure", "ui_unhealthy", "resolver_missing", "resolver_empty",
        "coop_unavailable", "coop_invalid_json", "coop_wrong_shape",
        # Public list degrades to seeds before v1.3; the header must still fail the deploy.
        "coop_unmigrated", "coop_no_header",
    ],
)
def test_deploy_fails_closed(scenario: str) -> None:
    result = _run_deploy(scenario)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Deploy done" not in result.stdout
    if scenario == "compose_failure":
        assert "docker compose failed" in result.stdout
        assert "REVIEW_PROBE:" not in result.stdout
    else:
        assert "deploy checks failed" in result.stdout


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell 5 unavailable")
def test_deploy_acceptance_with_windows_powershell_5(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy PowerShell must execute UTF-8 comments/code, not silently skip compose."""
    monkeypatch.setitem(globals(), "POWERSHELL", shutil.which("powershell.exe"))
    for scenario in ("success", "transient"):
        test_deploy_requires_all_readonly_acceptance_probes(scenario)
    for scenario in (
        "compose_failure", "warming", "empty_index", "empty_bm25", "invalid_json",
        "api_unavailable", "network_failure", "ui_unhealthy", "resolver_missing", "resolver_empty",
        "coop_unavailable", "coop_invalid_json", "coop_wrong_shape", "coop_unmigrated", "coop_no_header",
    ):
        test_deploy_fails_closed(scenario)
