# scripts/stop_stack.ps1 - clean shutdown for the NEU-Compass stack.
#
# Kills uvicorn + streamlit inside WSL and cloudflared on Windows. Idempotent —
# safe to run when nothing is running.
#
# Usage:
#   scripts\stop_stack.ps1
#   scripts\stop_stack.ps1 -KeepCloudflared   # only stop WSL services

[CmdletBinding()]
param(
    [switch]$KeepCloudflared,
    [string]$WslDistro = 'Ubuntu-24.04'
)

$ErrorActionPreference = 'Continue'   # don't abort on a single failure

Write-Host ''
Write-Host '=== Stopping NEU-Compass stack ===' -ForegroundColor Cyan
Write-Host ''

# === 1) WSL: uvicorn + streamlit ===
Write-Host '[1/3] Stopping uvicorn + streamlit in WSL' -ForegroundColor Yellow

# Kept single-line: multi-line strings lose their quoting going through
# powershell -> wsl.exe -> bash -lc. Single-quoted grep regex prevents bash
# from parsing the parens as a subshell. xargs -r skips no-input case.
# `$2` etc. are escaped with backtick so PowerShell doesn't try to expand them.
$grepPat = "'(api\.main:app|streamlit_app\.py|streamlit run app/)'"
# bash `[[ ]]` is used instead of `[ ]` because the enclosing PowerShell -> wsl.exe
# -> bash -lc bridge eats the inner double-quotes; `[ -n $X ]` (unquoted, $X empty)
# evaluates true because POSIX test sees a single non-empty token "-n". `[[ ]]` is
# parsed by bash itself and handles unquoted empty vars correctly.
$bash    = "PIDS=`$(ps -ef 2>/dev/null | grep -E $grepPat | grep -v grep | awk '{print `$2}'); " +
           "if [[ -n `$PIDS ]]; then echo killing PIDS=`$PIDS; " +
           "kill `$PIDS 2>/dev/null; sleep 2; " +
           "REMAINING=`$(ps -ef 2>/dev/null | grep -E $grepPat | grep -v grep | awk '{print `$2}'); " +
           "if [[ -n `$REMAINING ]]; then kill -9 `$REMAINING 2>/dev/null; fi; " +
           "echo stopped; else echo '(nothing to stop)'; fi"

$wslOut = wsl -d $WslDistro -e bash -lc $bash 2>&1
foreach ($line in @($wslOut)) { Write-Host "  $line" }

# === 2) Windows: cloudflared ===
if (-not $KeepCloudflared) {
    Write-Host '[2/3] Stopping cloudflared on Windows' -ForegroundColor Yellow
    $procs = Get-Process cloudflared -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force
        Write-Host "  stopped $($procs.Count) cloudflared process(es)"
    } else {
        Write-Host '  (nothing to stop)'
    }
} else {
    Write-Host '[2/3] cloudflared kept alive (-KeepCloudflared)' -ForegroundColor DarkGray
}

# === 2.5) Close the spawned PowerShell windows themselves ===
# start_stack records the spawned powershell.exe PIDs in scripts\.stack_pids
# (console window titles aren't exposed via .NET MainWindowTitle, so PID
# tracking is the reliable hook).
$pidFile = Join-Path $PSScriptRoot '.stack_pids'
if (Test-Path $pidFile) {
    $pids = Get-Content $pidFile | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ }
    $closed = 0
    foreach ($pid_ in $pids) {
        $proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
            $closed++
        }
    }
    if ($closed -gt 0) { Write-Host "  closed $closed leftover stack window(s)" }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

# === 3) Verify ports freed ===
Write-Host '[3/3] Verifying ports freed' -ForegroundColor Yellow
$stillBound = $false
foreach ($port in 8000, 8501) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pid_ = $conn.OwningProcess | Select-Object -First 1
        Write-Host "  ! port $port still bound (PID $pid_)" -ForegroundColor Yellow
        $stillBound = $true
    } else {
        Write-Host "  OK port $port freed"
    }
}

Write-Host ''
if ($stillBound) {
    Write-Host 'Some ports still bound. Check the new windows manually or rerun.' -ForegroundColor Yellow
} else {
    Write-Host 'Done.' -ForegroundColor Green
}
Write-Host ''
