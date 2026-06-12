# scripts/deploy.ps1 - Push NEU-Compass from PC dev box to the NAS.
#
# What this does (in order):
#   1. Pre-flight: verify Tailscale, WSL, NAS SSH reachable, NAS dirs exist
#   2. tar-pipe working tree → ${NasUser}@${NasHost}:${NasPath}/
#   3. scp .env             → ${NasUser}@${NasHost}:${NasPath}/.env
#   4. (opt-in) tar-pipe runtime data via WSL → ${NasPath}/runtime-data/
#   5. ssh nas "docker compose up -d [--build]"
#   6. Probe http://${NasHost}:8000/ready via Tailscale
#
# Why tar-pipe instead of rsync?
#   The UGREEN DXP NAS wraps /usr/bin/rsync with an ACL that only allows
#   paths configured as rsync modules — arbitrary destinations like
#   /volume1/docker/neu-compass/ get "invalid path" errors. tar-pipe over
#   ssh bypasses that wrapper entirely. Cost: no delta sync. For the small
#   working tree this is fine; the big runtime-data is opt-in via -SyncData.
#
# Usage:
#   scripts\deploy.ps1                      # code + .env + compose up --build
#   scripts\deploy.ps1 -SyncData            # ALSO push ~/neu-compass-data
#   scripts\deploy.ps1 -SkipCode            # data-only push (rare)
#   scripts\deploy.ps1 -NoBuild             # skip docker rebuild
#   scripts\deploy.ps1 -DryRun              # report what would happen, no transfer
#   scripts\deploy.ps1 -Force               # skip the confirmation prompt
#
# First-time NAS setup (already done — kept here for reference):
#   ssh ${NasUser}@${NasHost} 'mkdir -p /volume1/docker/neu-compass/{runtime-data,cloudflared}'
#   scp -O ~/.cloudflared/{cert.pem,*.json,config.yml} ${NasUser}@${NasHost}:/volume1/docker/neu-compass/cloudflared/
#   # Edit NAS config.yml: change service URLs from http://localhost:... to
#   # http://api:8000 and http://ui:8501 (compose service names).
#   ssh -t ${NasUser}@${NasHost} sudo usermod -aG docker ${NasUser}
#
# Env var defaults (set in your PowerShell $PROFILE to avoid passing each time):
#   $env:NEU_NAS_HOST = 'simonshen'
#   $env:NEU_NAS_USER = 'shenhaowei'
#   $env:NEU_NAS_PATH = '/volume1/docker/neu-compass'

[CmdletBinding()]
param(
    [string]$NasHost     = $(if ($env:NEU_NAS_HOST) { $env:NEU_NAS_HOST } else { 'simonshen' }),
    [string]$NasUser     = $(if ($env:NEU_NAS_USER) { $env:NEU_NAS_USER } else { 'shenhaowei' }),
    [string]$NasPath     = $(if ($env:NEU_NAS_PATH) { $env:NEU_NAS_PATH } else { '/volume1/docker/neu-compass' }),
    [string]$WslDistro   = 'Ubuntu-24.04',
    [string]$WslDataDir  = '~/neu-compass-data',
    [switch]$SyncData,                     # opt-in: also push runtime-data (~2.3GB)
    [switch]$SkipCode,
    [switch]$NoBuild,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProjectRoot   = 'H:\neu-compass'
$WslProject    = '/mnt/h/neu-compass'
$NasTarget     = "${NasUser}@${NasHost}"

Write-Host ''
Write-Host '=== NEU-Compass deploy ===' -ForegroundColor Cyan
Write-Host "  target  : $NasTarget"
Write-Host "  path    : $NasPath"
Write-Host "  code    : $(if ($SkipCode) {'SKIP'} else {'sync'})"
Write-Host "  .env    : $(if ($SkipCode) {'SKIP'} else {'sync'})"
Write-Host "  data    : $(if ($SyncData) {'sync (~2.3GB)'} else {'skip (-SyncData to include)'})"
Write-Host "  build   : $(if ($NoBuild) {'skip'} else {'docker compose up -d --build'})"
Write-Host "  dry-run : $DryRun"
Write-Host ''

# === 1) Pre-flight ===
Write-Host '[1/5] Pre-flight' -ForegroundColor Yellow

# Tailscale connectivity (best-effort: Windows tailscale.exe optional)
if (Get-Command tailscale.exe -ErrorAction SilentlyContinue) {
    & tailscale.exe status > $null 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Host '  OK tailscale up' } else { Write-Host '  ! tailscale CLI reports not up (continuing)' -ForegroundColor Yellow }
} else {
    Write-Host '  - tailscale CLI not in PATH (relying on DNS)' -ForegroundColor DarkGray
}

# Native ssh (Windows OpenSSH) to NAS — used for .env scp, compose, health probe
$sshTest = & ssh -o BatchMode=yes -o ConnectTimeout=5 "$NasTarget" 'echo ok' 2>&1
if ($LASTEXITCODE -ne 0 -or ($sshTest -join '') -notmatch 'ok') {
    Write-Host "  X cannot SSH to $NasTarget (key auth required, no password prompt)" -ForegroundColor Red
    Write-Host '    fix: type %USERPROFILE%\.ssh\id_ed25519.pub | ssh ${NasTarget} "..."' -ForegroundColor DarkGray
    exit 1
}
Write-Host "  OK native ssh -> $NasTarget"

# WSL ssh (needed only for tar-pipe code + data; uses key copied into WSL home)
if (-not $SkipCode -or $SyncData) {
    $wslSsh = wsl -d $WslDistro -e ssh -o BatchMode=yes -o ConnectTimeout=5 "$NasTarget" 'echo ok' 2>&1
    if ($LASTEXITCODE -ne 0 -or ($wslSsh -join '') -notmatch 'ok') {
        Write-Host "  X WSL ssh to $NasTarget failed (need ~/.ssh/id_ed25519 inside WSL too)" -ForegroundColor Red
        Write-Host '    fix: cp /mnt/c/Users/*/.ssh/id_ed25519* ~/.ssh/ && chmod 600 ~/.ssh/id_ed25519' -ForegroundColor DarkGray
        exit 1
    }
    Write-Host "  OK WSL ssh -> $NasTarget"
}

# NAS target dirs
$dirCheck = & ssh "$NasTarget" "test -d '$NasPath' && test -d '$NasPath/runtime-data' && test -d '$NasPath/cloudflared' && echo ok" 2>&1
if (($dirCheck -join '') -notmatch 'ok') {
    Write-Host "  X NAS dirs missing under $NasPath. First-time setup needed (see header comment)" -ForegroundColor Red
    exit 1
}
Write-Host "  OK NAS dirs at $NasPath"

# .env present locally
if (-not $SkipCode -and -not (Test-Path (Join-Path $ProjectRoot '.env'))) {
    Write-Host '  X local .env missing — cannot deploy secrets' -ForegroundColor Red
    exit 1
}
if (-not $SkipCode) { Write-Host '  OK local .env present' }

# === 2) Confirmation ===
if (-not $Force -and -not $DryRun) {
    Write-Host ''
    $answer = Read-Host "Proceed with deploy? [y/N]"
    if ($answer -notmatch '^[Yy]') {
        Write-Host 'Aborted.' -ForegroundColor Yellow
        exit 0
    }
}

# Exclusion list for code tar — mirrors .dockerignore
$tarExcludes = @(
    '--exclude=.git',
    '--exclude=.venv',
    '--exclude=__pycache__',
    '--exclude=*.py[cod]',
    '--exclude=.pytest_cache',
    '--exclude=.mypy_cache',
    '--exclude=.ruff_cache',
    '--exclude=.coverage',
    '--exclude=tests',
    '--exclude=eval',
    '--exclude=docs',
    '--exclude=backups',
    '--exclude=data/raw',
    '--exclude=data/processed',
    '--exclude=data/ground_truth',
    '--exclude=data/coop_seed/curated.json',
    '--exclude=*.db',
    '--exclude=*.db-*',
    '--exclude=*.faiss',
    '--exclude=faiss_index',
    '--exclude=runtime-data',
    '--exclude=cloudflared',
    '--exclude=.env',
    '--exclude=scripts/.stack_pids',
    '--exclude=*.log',
    '--exclude=*.ipynb',
    '--exclude=.ipynb_checkpoints'
) -join ' '

# === 3) Code: tar -czf - | ssh "tar -xzf - -C dest" ===
if (-not $SkipCode) {
    Write-Host ''
    Write-Host '[2/5] tar-pipe code -> NAS' -ForegroundColor Yellow
    if ($DryRun) {
        # tar --totals writes "Total bytes written" to stderr after packing — gives a real size estimate
        $est = wsl -d $WslDistro -e bash -lc "cd $WslProject && tar $tarExcludes --totals -czf /dev/null . 2>&1 | grep -i 'Total bytes'"
        Write-Host "  would tar-pipe code: $est"
    } else {
        $tarCmd = "cd $WslProject && tar $tarExcludes -czf - . | ssh $NasTarget 'tar -xzf - -C $NasPath/ && echo OK'"
        $out = wsl -d $WslDistro -e bash -lc "$tarCmd" 2>&1
        if ($LASTEXITCODE -ne 0 -or ($out -join '') -notmatch 'OK') {
            Write-Host "  X tar-pipe failed: $out" -ForegroundColor Red
            exit 1
        }
        Write-Host '  OK code transferred'
    }
}

# === 4) .env: native scp -O ===
if (-not $SkipCode) {
    Write-Host ''
    Write-Host '[3/5] scp .env -> NAS' -ForegroundColor Yellow
    if ($DryRun) {
        Write-Host '  (dry-run skipped)'
    } else {
        & scp -O (Join-Path $ProjectRoot '.env') "${NasTarget}:${NasPath}/.env" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Host '  X scp .env failed' -ForegroundColor Red; exit 1 }
        Write-Host '  OK .env transferred'
    }
}

# === 5) runtime-data: opt-in tar-pipe (no compression — ONNX FP16 doesn't compress) ===
if ($SyncData) {
    Write-Host ''
    Write-Host "[4/5] tar-pipe runtime-data ($WslDataDir) -> NAS (~2.3GB)" -ForegroundColor Yellow
    if ($DryRun) {
        wsl -d $WslDistro -e bash -lc "du -sh $WslDataDir/courses.db $WslDataDir/faiss_index $WslDataDir/onnx" | ForEach-Object { Write-Host "  $_" }
        Write-Host '  (dry-run: would transfer above)'
    } else {
        # Sync everything in ~/neu-compass-data/ except local benchmark artifacts
        # (eval_results/, TOP-LEVEL *.json probes, raw/). Picks up new dirs like
        # openvino/ automatically without needing this script edited each time.
        #
        # CRITICAL: the json exclude must be anchored to ./*.json (top level
        # only). A bare --exclude='*.json' matched at ANY depth and silently
        # dropped faiss_index/id_map.json (FaissIndex.load hard-requires it;
        # a STALE copy mis-maps int ids -> wrong courses with no error) and
        # every OpenVINO model dir's config.json (from_pretrained refuses to
        # load -> api crash-loops, ui+cloudflared never start).
        $dataCmd = "cd $WslDataDir && tar --anchored --exclude='./eval_results' --exclude='./*.json' --exclude='./raw' -cf - . 2>/dev/null | ssh $NasTarget 'tar -xf - -C $NasPath/runtime-data/ && echo OK'"
        $out = wsl -d $WslDistro -e bash -lc "$dataCmd" 2>&1
        if ($LASTEXITCODE -ne 0 -or ($out -join '') -notmatch 'OK') {
            Write-Host "  X runtime-data tar-pipe failed: $out" -ForegroundColor Red
            exit 1
        }
        Write-Host '  OK runtime-data transferred'
    }
} else {
    Write-Host '[4/5] runtime-data skipped (pass -SyncData to include)' -ForegroundColor DarkGray
}

# === 6) docker compose ===
Write-Host ''
Write-Host '[5/5] docker compose on NAS' -ForegroundColor Yellow
if ($DryRun) {
    Write-Host '  (dry-run skipped)'
} else {
    $composeCmd = if ($NoBuild) { 'docker compose up -d' } else { 'docker compose up -d --build' }
    & ssh "$NasTarget" "cd '$NasPath' && $composeCmd 2>&1 | tail -15"
    if ($LASTEXITCODE -ne 0) { Write-Host '  X docker compose failed' -ForegroundColor Red; exit 1 }

    # Health probe via Tailscale (faster feedback than waiting on public CF)
    Write-Host ''
    Write-Host "  Probing http://${NasHost}:8000/ready (180s timeout) " -NoNewline
    $deadline = (Get-Date).AddSeconds(180)
    $ok = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest "http://${NasHost}:8000/ready" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            if ($r.StatusCode -eq 200) { $ok = $true; break }
        } catch { }
        Write-Host -NoNewline '.'
        Start-Sleep -Seconds 3
    }
    Write-Host ''
    if ($ok) {
        Write-Host '  OK NAS api /ready 200' -ForegroundColor Green
    } else {
        Write-Host '  ! NAS api did not reach /ready in 180s — check logs:' -ForegroundColor Yellow
        Write-Host "    ssh $NasTarget 'cd $NasPath && docker compose logs --tail=100 api'" -ForegroundColor DarkGray
    }
}

Write-Host ''
Write-Host '=== Deploy done ===' -ForegroundColor Green
Write-Host ''
Write-Host '  Public:'
Write-Host '    https://api.neu-compass.me/health'
Write-Host '    https://compass.neu-compass.me'
Write-Host ''
Write-Host "  Logs:  ssh $NasTarget 'cd $NasPath && docker compose logs -f api'"
Write-Host ''
