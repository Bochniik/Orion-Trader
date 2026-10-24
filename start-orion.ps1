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

# Retain the Process object returned by Start-Process: stopping by PID alone
# could target a different process if Windows has recycled the PID.
function Stop-OwnedProcess($Process) {
    if ($null -eq $Process) { return }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) {
            $Process.Kill()
        }
    }
    catch {
        Write-Warning "Could not stop a process owned by this launch; inspect its terminal."
    }
}

# Do not inherit a stale bridge opt-in from an earlier terminal session.
# Explicit -StartOurAI is required for this managed launcher.
$env:OURAI_BRIDGE_ENABLED = "false"
$env:OURAI_BRIDGE_PORT = "8765"

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
            Stop-OwnedProcess $ouraiProcess
        }
        throw "OurAI bridge did not return verified read-only evidence. Orion was not started."
    }
    $env:OURAI_BRIDGE_ENABLED = "true"
    $env:OURAI_BRIDGE_PORT = "8765"
    Write-Host "OurAI verified read-only bridge ready (PID $($ouraiProcess.Id))." -ForegroundColor Cyan
    Write-Host "Stop the OurAI process separately when finished; automatic lifecycle management is not implemented yet." -ForegroundColor Yellow
}

Write-Host "Starting OrionTrader backend and frontend..." -ForegroundColor Cyan
$backendProcess = $null
$frontendProcess = $null
try {
    # A managed opt-in launch must own the actual server processes. Uvicorn
    # --reload forks a worker, and npm.cmd launches a separate Node child;
    # killing their wrapper PIDs can leave ports 8000/5173 occupied on failure.
    $backendArguments = @("-m", "uvicorn", "app.main:app", "--port", "8000")
    if (-not $StartOurAI) { $backendArguments += "--reload" }
    $backendProcess = Start-Process -FilePath $venvPython `
        -ArgumentList $backendArguments `
        -WorkingDirectory $backend -PassThru
    if ($StartOurAI) {
        Require-Command "node.exe" "Node.js is required for managed local startup."
        $viteEntry = Join-Path $frontend "node_modules\\vite\\bin\\vite.js"
        if (-not (Test-Path -LiteralPath $viteEntry -PathType Leaf)) {
            throw "Vite entry point is missing; reinstall frontend dependencies."
        }
        # Quote the entry path because the repository may live under Program Files.
        $frontendProcess = Start-Process -FilePath "node.exe" `
            -ArgumentList "`"$viteEntry`"", "--host", "127.0.0.1", "--port", "5173", "--strictPort" `
            -WorkingDirectory $frontend -PassThru
    }
    else {
        # Preserve the existing development workflow unless opted in.
        $frontendProcess = Start-Process -FilePath "npm.cmd" `
            -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort" `
            -WorkingDirectory $frontend -PassThru
    }
}
catch {
    if ($StartOurAI) {
        foreach ($ownedProcess in @($frontendProcess, $backendProcess, $ouraiProcess)) {
            if ($null -ne $ownedProcess -and -not $ownedProcess.HasExited) {
                Stop-OwnedProcess $ownedProcess
            }
        }
    }
    throw
}

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
    if ($StartOurAI) {
        # Do not leave an opt-in bridge running after a failed Orion startup.
        # Only terminate the exact processes this launcher started.
        foreach ($ownedProcess in @($frontendProcess, $backendProcess, $ouraiProcess)) {
            if ($null -ne $ownedProcess -and -not $ownedProcess.HasExited) {
                Stop-OwnedProcess $ownedProcess
            }
        }
        throw "Orion backend did not become ready; attempted to stop the processes started by this launch."
    }
    Write-Warning "The backend did not become ready in time. Check the backend window for details."
}

# Backend health alone does not establish that the Vite UI is serving this launch.
# In opt-in mode, a missing frontend must also fail closed and stop owned
# processes rather than report a successful integrated startup.
$frontendReady = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ($frontendProcess.HasExited) { break }
    try {
        $frontendResponse = Invoke-WebRequest -Uri "http://127.0.0.1:5173/" -UseBasicParsing -TimeoutSec 1
        if ($frontendResponse.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    }
    catch {
        # The UI may still be starting; retry without trusting another port.
    }
    Start-Sleep -Milliseconds 500
}

if (-not $frontendReady) {
    if ($StartOurAI) {
        foreach ($ownedProcess in @($frontendProcess, $backendProcess, $ouraiProcess)) {
            if ($null -ne $ownedProcess -and -not $ownedProcess.HasExited) {
                Stop-OwnedProcess $ownedProcess
            }
        }
        throw "Orion frontend did not become ready; attempted to stop the processes started by this launch."
    }
    Write-Warning "The frontend did not become ready in time. Check the frontend window for details."
}

Write-Host "Backend PID: $($backendProcess.Id) | Frontend PID: $($frontendProcess.Id)" -ForegroundColor DarkGray
Write-Host "OrionTrader: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "API docs:    http://127.0.0.1:8000/docs" -ForegroundColor Green

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:5173"
}
