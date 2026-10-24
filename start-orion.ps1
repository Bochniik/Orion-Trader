[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$NoBrowser,
    [switch]$StartOurAI,
    [string]$OurAIPath = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$viteCommand = Join-Path $frontend "node_modules\.bin\vite.cmd"
$envFile = Join-Path $backend ".env"
$envExample = Join-Path $backend ".env.example"

function Require-Command([string]$Name, [string]$InstallHint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

function Assert-PortAvailable([int]$Port, [string]$ServiceName) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $listener) {
        return
    }

    $processLabel = "PID $($listener.OwningProcess)"
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($owner) {
        $processLabel = "$($owner.ProcessName) (PID $($owner.Id))"
    }

    throw "$ServiceName cannot start because port $Port is already used by $processLabel. Close the old OrionTrader terminal or stop that process, then run this launcher again."
}

Require-Command "npm.cmd" "Install the current Node.js LTS release and reopen PowerShell."

if (-not (Test-Path $venvPython)) {
    if ($SkipInstall) {
        throw "Python environment is missing. Run .\start-orion.ps1 once without -SkipInstall."
    }

    Require-Command "py.exe" "Install Python 3.11 or newer and enable the Python launcher."
    Write-Host "Creating the Python environment..." -ForegroundColor Cyan
    & py.exe -3 -m venv (Join-Path $root ".venv")
}

if (-not $SkipInstall) {
    Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
    & $venvPython -m pip install -r (Join-Path $backend "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }

    if (-not (Test-Path $viteCommand)) {
        Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
        Push-Location $frontend
        try {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        }
        finally {
            Pop-Location
        }
    }
}

if (-not (Test-Path $viteCommand)) {
    throw "Frontend dependencies are missing. Run .\start-orion.ps1 without -SkipInstall."
}

if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "Created backend\.env. Add OPENAI_API_KEY there to enable Orion AI." -ForegroundColor Yellow
}

# Vite normally chooses another port when 5173 is occupied. That can leave the
# browser on an older Orion frontend while it talks to the newly started API.
# Fail before starting either service so the pair always belongs to one launch.
Assert-PortAvailable 8000 "OrionTrader backend"
Assert-PortAvailable 5173 "OrionTrader frontend"

# Transitional opt-in local startup. Future packaged builds will provide an
# embedded OurAI runtime; never silently trust or execute an arbitrary folder.
if ($StartOurAI) {
    if ([string]::IsNullOrWhiteSpace($OurAIPath)) {
        throw "-StartOurAI requires an explicit trusted -OurAIPath. Nothing was started."
    }
    $ouraiRoot = (Resolve-Path -LiteralPath $OurAIPath -ErrorAction Stop).Path
    $ouraiScript = Join-Path $ouraiRoot "scripts\serve_orion_forward_bridge.py"
    if (-not (Test-Path -LiteralPath $ouraiScript -PathType Leaf)) {
        throw "OurAI read-only server script not found at the selected path."
    }
    Assert-PortAvailable 8765 "OurAI read-only bridge"
    $ouraiPython = Join-Path $ouraiRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $ouraiPython -PathType Leaf)) {
        throw "OurAI Python environment is missing. Install it in the selected OurAI directory first."
    }
    # The server only binds to 127.0.0.1, reads the verified journal and
    # cannot place trades. Child environment enables the Orion read-only client.
    $ouraiProcess = Start-Process -FilePath $ouraiPython `
        -ArgumentList "-m", "scripts.serve_orion_forward_bridge", "--port", "8765" `
        -WorkingDirectory $ouraiRoot -PassThru
    $ouraiReady = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if ($ouraiProcess.HasExited) { break }
        try {
            $evidence = Invoke-RestMethod -Uri "http://127.0.0.1:8765/v1/forward-evidence" -TimeoutSec 2
            if ($evidence.schema_version -eq 1 -and
                $evidence.source -eq "ourai_verified_forward_journal" -and
                $evidence.journal_valid -eq $true -and
                $evidence.experiment -eq "frozen_v3_magnitude_15m" -and
                $evidence.mode -eq "RESEARCH_SHADOW_ONLY" -and
                $evidence.horizon_minutes -eq 15 -and
                $evidence.trading_enabled -eq $false -and
                $evidence.direction_available -eq $false) {
                $ouraiReady = $true
                break
            }
        }
        catch {
            # Missing or invalid evidence is not a successful startup.
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ouraiReady) {
        if (-not $ouraiProcess.HasExited) {
            Stop-Process -Id $ouraiProcess.Id -ErrorAction SilentlyContinue
        }
        throw "OurAI bridge did not return verified read-only evidence. Orion was not started."
    }
    $env:OURAI_BRIDGE_ENABLED = "true"
    $env:OURAI_BRIDGE_PORT = "8765"
    Write-Host "OurAI verified read-only bridge ready (PID $($ouraiProcess.Id))." -ForegroundColor Cyan
    Write-Host "Stop the OurAI process separately when finished; automatic lifecycle management is not implemented yet." -ForegroundColor Yellow
}

Write-Host "Starting OrionTrader backend and frontend..." -ForegroundColor Cyan
$backendProcess = Start-Process -FilePath $venvPython `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000" `
    -WorkingDirectory $backend -PassThru
$frontendProcess = Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort" `
    -WorkingDirectory $frontend -PassThru

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 1
        if ($health.status -eq "ok") {
            $ready = $true
            break
        }
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $ready) {
    Write-Warning "The backend did not become ready in time. Check the backend window for details."
}

Write-Host "Backend PID: $($backendProcess.Id) | Frontend PID: $($frontendProcess.Id)" -ForegroundColor DarkGray
Write-Host "OrionTrader: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "API docs:    http://127.0.0.1:8000/docs" -ForegroundColor Green

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:5173"
}
