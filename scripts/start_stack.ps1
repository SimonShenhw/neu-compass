# scripts/start_stack.ps1 - one-click launch for the NEU-Compass production stack.
#
# Spawns three new PowerShell windows so each service's log is visible:
#   1. WSL: uvicorn   (FastAPI backend on :8000, ONNX backend by default ~6s warm)
#   2. WSL: streamlit (UI on :8501)
#   3. Win: cloudflared (tunnel `neu-compass` -> api.neu-compass.me + compass.neu-compass.me)
#
# Usage:
#   scripts\start_stack.ps1                # full stack (default)
#   scripts\start_stack.ps1 -Local         # local only (skip cloudflared)
#   scripts\start_stack.ps1 -Pytorch       # PyTorch backend (~70s warm)
#   scripts\start_stack.ps1 -ApiOnly       # uvicorn only
#
# Stop with: scripts\stop_stack.ps1

[CmdletBinding()]
param(
    [switch]$Local,                        # alias for -NoCloudflared
    [switch]$NoCloudflared,
    [switch]$NoStreamlit,
    [switch]$ApiOnly,                      # uvicorn only (implies -NoStreamlit -NoCloudflared)
    [switch]$Pytorch,                      # use pytorch backend instead of ONNX
    [string]$WslDistro = 'Ubuntu-24.04',
    [string]$TunnelName = 'neu-compass'
)

$ErrorActionPreference = 'Stop'

$ProjectRoot   = 'H:\neu-compass'
$WslProject    = '/mnt/h/neu-compass'
$DataDir       = '~/neu-compass-data'   # in WSL home (ADR-0014)

if ($ApiOnly) { $NoStreamlit = $true; $NoCloudflared = $true }
if ($Local)   { $NoCloudflared = $true }

Write-Host ''
Write-Host '=== NEU-Compass stack launcher ===' -ForegroundColor Cyan
Write-Host ''

# === 1) Pre-flight ===
Write-Host '[1/4] Pre-flight checks' -ForegroundColor Yellow

$bad = $false

# .env present
$envFile = Join-Path $ProjectRoot '.env'
if (-not (Test-Path $envFile)) {
    Write-Host "  X .env missing at $envFile" -ForegroundColor Red
    Write-Host '    fix: cp .env.example .env  &&  fill in keys' -ForegroundColor DarkGray
    $bad = $true
} else {
    Write-Host "  OK .env present"
}

# WSL reachable
try {
    $wslVer = wsl -d $WslDistro -e bash -lc 'echo ok' 2>&1
    if ($LASTEXITCODE -ne 0 -or $wslVer -notmatch 'ok') {
        Write-Host "  X cannot reach WSL distro '$WslDistro'" -ForegroundColor Red
        $bad = $true
    } else {
        Write-Host "  OK WSL distro '$WslDistro' reachable"
    }
} catch {
    Write-Host "  X wsl command failed: $_" -ForegroundColor Red
    $bad = $true
}

# SQLite + FAISS present
if (-not $bad) {
    $dbCheck = wsl -d $WslDistro -e bash -lc "ls $DataDir/courses.db $DataDir/faiss_index/index.faiss 2>&1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  X SQLite or FAISS index missing in ~/neu-compass-data/' -ForegroundColor Red
        Write-Host '    fix: re-run scripts/ingest_neu_catalog.py + scripts/rebuild_faiss.py' -ForegroundColor DarkGray
        $bad = $true
    } else {
        Write-Host '  OK SQLite + FAISS index present'
    }
}

# ONNX models present (unless -Pytorch)
if (-not $bad -and -not $Pytorch) {
    $onnxCheck = wsl -d $WslDistro -e bash -lc "ls $DataDir/onnx/embedder/model.onnx $DataDir/onnx/reranker/model.onnx 2>&1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  X ONNX models missing in ~/neu-compass-data/onnx/' -ForegroundColor Red
        Write-Host '    fix: uv run python scripts/export_models_onnx.py --fp16' -ForegroundColor DarkGray
        Write-Host '    or pass -Pytorch to skip ONNX (~70s warmup vs ~6s)' -ForegroundColor DarkGray
        $bad = $true
    } else {
        Write-Host '  OK ONNX embedder + reranker present'
    }
}

# cloudflared.exe in PATH (unless -NoCloudflared)
if (-not $bad -and -not $NoStreamlit) {
    # Streamlit's first-run "Welcome ... Email:" prompt blocks on stdin and
    # hangs forever in a non-tty subshell. The `--server.headless` flag does
    # NOT skip this gate — only credentials.toml does. Delegate to a real .sh
    # so PowerShell-bash quote translation can't lose the heredoc.
    $ensureOut = wsl -d $WslDistro -e bash "$WslProject/scripts/ensure_streamlit_cfg.sh" 2>&1
    if (($ensureOut -join "`n") -match 'OK') {
        Write-Host '  OK Streamlit config (credentials.toml + config.toml) ensured'
    } else {
        Write-Host "  ! could not ensure Streamlit config: $ensureOut" -ForegroundColor Yellow
    }
}

if (-not $bad -and -not $NoCloudflared) {
    $cf = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (-not $cf) {
        Write-Host '  X cloudflared.exe not in PATH' -ForegroundColor Red
        Write-Host '    fix: winget install Cloudflare.cloudflared   (or pass -Local)' -ForegroundColor DarkGray
        $bad = $true
    } else {
        Write-Host "  OK cloudflared.exe at $($cf.Source)"
    }

    # Tunnel credentials
    $cfDir = Join-Path $env:USERPROFILE '.cloudflared'
    if (-not (Test-Path (Join-Path $cfDir 'config.yml'))) {
        Write-Host "  X cloudflared config.yml missing at $cfDir" -ForegroundColor Red
        Write-Host '    fix: see docs/cloudflare_tunnel.md section 3' -ForegroundColor DarkGray
        $bad = $true
    } else {
        Write-Host "  OK cloudflared config at $cfDir"
    }
}

# Port collisions (warn, don't fail — user might intend a restart)
foreach ($port in 8000, 8501) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pid_ = $conn.OwningProcess | Select-Object -First 1
        Write-Host "  ! port $port already listening (PID $pid_) - run scripts\stop_stack.ps1 first?" -ForegroundColor Yellow
    }
}

if ($bad) {
    Write-Host ''
    Write-Host 'Pre-flight failed. Resolve the above and retry.' -ForegroundColor Red
    exit 1
}

Write-Host ''

# === 2) Build per-service WSL command strings (single-quoted = no PS expansion) ===

# Inference backend env: ONNX (fast) by default, PyTorch fallback via -Pytorch.
# Single quotes prevent PowerShell from expanding $HOME — bash gets it literally.
$inferenceEnv = if ($Pytorch) {
    ''
} else {
    'INFERENCE_BACKEND=onnx ONNX_MODEL_DIR=$HOME/neu-compass-data/onnx ONNX_PROVIDERS=CUDAExecutionProvider '
}

$uvicornBash   = "cd $WslProject && env $inferenceEnv uv run uvicorn api.main:app --host 0.0.0.0 --port 8000"
$streamlitBash = "cd $WslProject && uv run streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false"

# === 3) Spawn windows ===
# We track the spawned PowerShell.exe PIDs in a state file so stop_stack
# can close the leftover -NoExit windows. (The console window's title isn't
# exposed via .NET MainWindowTitle, so PID-tracking is the reliable hook.)
$pidFile = Join-Path $ProjectRoot 'scripts\.stack_pids'
Set-Content -Path $pidFile -Value '' -Encoding ASCII

Write-Host '[2/4] Starting uvicorn (port 8000) in new window' -ForegroundColor Yellow

$uvicornWin = "`$Host.UI.RawUI.WindowTitle = 'neu-compass : uvicorn (api)' ; wsl -d $WslDistro -e bash -lc '$uvicornBash'"
$psProc = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoExit', '-Command', $uvicornWin) `
    -WindowStyle Normal -PassThru
Add-Content -Path $pidFile -Value $psProc.Id
$warmHint = if ($Pytorch) { '~70s' } else { '~6s + first-time HF metadata' }
Write-Host "  OK spawned (warmup $warmHint -> watch the new window for 'Application startup complete.')"

if (-not $NoStreamlit) {
    Write-Host '[3/4] Starting streamlit (port 8501) in new window' -ForegroundColor Yellow
    Start-Sleep -Seconds 2     # let uvicorn start binding 8000 first
    $streamlitWin = "`$Host.UI.RawUI.WindowTitle = 'neu-compass : streamlit (ui)' ; wsl -d $WslDistro -e bash -lc '$streamlitBash'"
    $psProc = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoExit', '-Command', $streamlitWin) `
        -WindowStyle Normal -PassThru
    Add-Content -Path $pidFile -Value $psProc.Id
    Write-Host '  OK spawned'
} else {
    Write-Host '[3/4] streamlit skipped (-NoStreamlit / -ApiOnly)' -ForegroundColor DarkGray
}

if (-not $NoCloudflared) {
    # Wait for uvicorn /ready before launching cloudflared. Otherwise the
    # tunnel comes up first, public health checks (and any in-flight user
    # request) hit the not-yet-bound port, and cloudflared spams ~50s of
    # red "connection refused" lines before uvicorn finishes its ONNX warmup.
    Write-Host '[4/4] Waiting for uvicorn /ready before starting cloudflared' -ForegroundColor Yellow
    $readyDeadline = (Get-Date).AddSeconds(180)
    $ready = $false
    Write-Host -NoNewline '  '
    while ((Get-Date) -lt $readyDeadline) {
        try {
            $r = Invoke-WebRequest 'http://localhost:8000/ready' -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        Write-Host -NoNewline '.'
        Start-Sleep -Seconds 3
    }
    Write-Host ''
    if (-not $ready) {
        Write-Host '  ! uvicorn did not reach /ready within 180s. Starting cloudflared anyway' -ForegroundColor Yellow
        Write-Host '    (tunnel will spam errors until origin comes up; check the uvicorn window)' -ForegroundColor DarkGray
    } else {
        $elapsed = [math]::Round(((Get-Date) - $readyDeadline.AddSeconds(-180)).TotalSeconds, 1)
        Write-Host "  OK uvicorn ready after ~${elapsed}s"
    }

    Write-Host '      Starting cloudflared tunnel in new window' -ForegroundColor Yellow
    $cfWin = "`$Host.UI.RawUI.WindowTitle = 'neu-compass : cloudflared (tunnel)' ; cloudflared tunnel run $TunnelName"
    $psProc = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoExit', '-Command', $cfWin) `
        -WindowStyle Normal -PassThru
    Add-Content -Path $pidFile -Value $psProc.Id
    Write-Host "  OK spawned (tunnel: $TunnelName)"
} else {
    Write-Host '[4/4] cloudflared skipped (-Local / -NoCloudflared / -ApiOnly)' -ForegroundColor DarkGray
}

# === 4) Summary ===
Write-Host ''
Write-Host '=== Stack launching ===' -ForegroundColor Green
Write-Host ''
Write-Host '  Local:'
Write-Host '    API        http://localhost:8000/health'
Write-Host '    /ready     http://localhost:8000/ready    (poll until 200)'
if (-not $NoStreamlit) {
    Write-Host '    Streamlit  http://localhost:8501'
}
if (-not $NoCloudflared) {
    Write-Host ''
    Write-Host '  Public (Cloudflare):'
    Write-Host '    API        https://api.neu-compass.me/health'
    Write-Host '    Streamlit  https://compass.neu-compass.me'
}
Write-Host ''
Write-Host '  Stop all:    scripts\stop_stack.ps1'
Write-Host '  Verify:      curl http://localhost:8000/ready'
Write-Host ''
