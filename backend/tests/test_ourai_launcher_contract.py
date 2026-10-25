"""Static regression guard for opt-in Windows OurAI launcher integration.

These checks do not replace a real Windows PowerShell end-to-end test.
"""
from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[2] / "start-orion.ps1"


def test_ourai_startup_is_explicit_opt_in_and_local():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "[switch]$StartOurAI" in source
    assert "if ($StartOurAI) {" in source
    assert "requires an explicit trusted -OurAIPath" in source
    assert 'Assert-PortAvailable 8765 "OurAI read-only bridge"' in source
    assert 'http://127.0.0.1:8765/v1/forward-evidence' in source


def test_ourai_readiness_is_checked_before_enabling_client():
    source = LAUNCHER.read_text(encoding="utf-8")
    readiness = source.index('$evidenceResponse = Invoke-WebRequest')
    checks = source.index('$evidence.journal_valid -eq $true')
    failure = source.index('throw "OurAI bridge did not return verified read-only evidence.')
    enable = source.index('$env:OURAI_BRIDGE_ENABLED = "true"')
    backend_start = source.index('$backendProcess = Start-Process')
    assert readiness < checks < failure < enable < backend_start
    assert '$evidence.trading_enabled -eq $false' in source
    assert '$evidence.direction_available -eq $false' in source
    assert 'Stop-OwnedProcess $ouraiProcess' in source


def test_no_trading_or_model_execution_added_to_launcher():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert '"scripts.serve_orion_forward_bridge"' in source
    assert "run_v3_forward_shadow" not in source
    assert "train_trading_baseline" not in source
    assert "place_order" not in source


def test_opt_in_startup_failure_cleans_up_only_owned_processes():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert 'Write-Host "Starting OrionTrader backend and frontend..."' in source
    launch_section = source.split('Write-Host "Starting OrionTrader backend and frontend..."', 1)[1]
    # Both a Start-Process exception and a failed backend health probe must
    # clean up the child processes created during this invocation.
    cleanup = 'foreach ($ownedProcess in @($frontendProcess, $backendProcess, $ouraiProcess))'
    assert launch_section.count(cleanup) == 3
    assert launch_section.count('Stop-OwnedProcess $ownedProcess') == 3
    assert 'if ($StartOurAI) {' in launch_section
    assert 'throw "Orion backend did not become ready;' in launch_section
    assert 'Write-Warning "The backend did not become ready in time.' in launch_section
    assert 'Stop-Process -Name' not in source
    assert 'Stop-Process -Id' not in source
    assert '$Process.Kill()' in source
    assert '$Process.Refresh()' in source
    assert 'Get-Process | Stop-Process' not in source


def test_launcher_clears_stale_environment_opt_in_before_startup():
    source = LAUNCHER.read_text(encoding="utf-8")
    reset = source.index('$env:OURAI_BRIDGE_ENABLED = "false"')
    managed = source.index("if ($StartOurAI) {")
    enabled = source.index('$env:OURAI_BRIDGE_ENABLED = "true"')
    assert reset < managed < enabled


def test_opt_in_launcher_requires_frontend_readiness_before_reporting_success():
    source = LAUNCHER.read_text(encoding="utf-8")
    frontend_probe = source.index('Invoke-WebRequest -Uri "http://127.0.0.1:5173/"')
    frontend_ready = source.index('$frontendResponse.StatusCode -eq 200')
    frontend_failure = source.index('throw "Orion frontend did not become ready;')
    frontend_warning = source.index('Write-Warning "The frontend did not become ready in time.')
    success_output = source.index('Write-Host "OrionTrader: http://127.0.0.1:5173"')
    browser_launch = source.index('Start-Process "http://127.0.0.1:5173"')
    assert frontend_probe < frontend_ready < frontend_failure < success_output < browser_launch
    assert frontend_failure < frontend_warning < success_output
    assert 'if ($frontendProcess.HasExited) { break }' in source
    assert 'if ($StartOurAI) {' in source[frontend_ready:frontend_failure]
    assert 'Stop-OwnedProcess $ownedProcess' in source[frontend_ready:frontend_failure]



def test_managed_opt_in_owns_server_processes_without_wrapper_children():
    """Source contract for rollback; Windows process-tree E2E still required."""
    source = LAUNCHER.read_text(encoding="utf-8")
    assert '$backendArguments = @("-m", "uvicorn", "app.main:app", "--port", "8000")' in source
    assert 'if (-not $StartOurAI) { $backendArguments += "--reload" }' in source
    assert '-ArgumentList $backendArguments' in source
    assert 'Require-Command "node.exe"' in source
    assert r'Join-Path $frontend "node_modules\vite\bin\vite.js"' in source
    assert '-FilePath "node.exe"' in source
    assert '-ArgumentList "`"$viteEntry`"", "--host", "127.0.0.1", "--port", "5173", "--strictPort"' in source
    assert '-FilePath "npm.cmd"' in source
    assert '"run", "dev", "--", "--host", "127.0.0.1"' in source
    # A missing Vite entry point must trigger cleanup of already-started backend.
    start = source.index('$backendArguments = @(')
    failure = source.index('throw "Vite entry point is missing;')
    cleanup = source.index('Stop-OwnedProcess $ownedProcess', failure)
    assert start < failure < cleanup



def test_managed_bridge_flag_is_scoped_to_spawned_backend_not_parent_shell():
    """Static guard: only the spawned backend inherits the verified opt-in."""
    source = LAUNCHER.read_text(encoding="utf-8")
    enabled = source.index('$env:OURAI_BRIDGE_ENABLED = "true"')
    backend_start = source.index('$backendProcess = Start-Process')
    parent_reset = source.index(
        '$env:OURAI_BRIDGE_ENABLED = "false"', backend_start
    )
    frontend_start = source.index('$frontendProcess = Start-Process', backend_start)
    assert enabled < backend_start < parent_reset < frontend_start

    # If backend creation raises before the normal reset, the catch must
    # still clear the parent flag and only then clean up owned processes.
    failure_handler = source.index('catch {', backend_start)
    failure_end = source.index('\n$ready = $false', failure_handler)
    failure_body = source[failure_handler:failure_end]
    assert '$env:OURAI_BRIDGE_ENABLED = "false"' in failure_body
    assert failure_body.index('$env:OURAI_BRIDGE_ENABLED = "false"') < failure_body.index(
        'Stop-OwnedProcess $ownedProcess'
    )


def test_managed_readiness_never_follows_redirects_outside_loopback():
    """Static guard for local-only bootstrap; Windows E2E remains required."""
    source = LAUNCHER.read_text(encoding="utf-8")
    probe = source.index('$evidenceResponse = Invoke-WebRequest')
    assert 'Invoke-WebRequest -Uri "http://127.0.0.1:8765/v1/forward-evidence"' in source
    assert '-UseBasicParsing -MaximumRedirection 0 -TimeoutSec 2' in source
    status = source.index('$evidenceResponse.StatusCode -ne 200', probe)
    decode = source.index('$evidence = ConvertFrom-Json -InputObject $evidenceResponse.Content', probe)
    checks = source.index('$evidence.journal_valid -eq $true', probe)
    enable = source.index('$env:OURAI_BRIDGE_ENABLED = "true"', probe)
    assert probe < status < decode < checks < enable


def test_managed_orion_readiness_never_follows_redirects():
    """Both local servers must return direct HTTP 200 before success is reported."""
    source = LAUNCHER.read_text(encoding="utf-8")

    backend_probe = source.index(
        '$healthResponse = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health"'
    )
    backend_status = source.index('$healthResponse.StatusCode -eq 200', backend_probe)
    backend_json = source.index(
        '$health = ConvertFrom-Json -InputObject $healthResponse.Content',
        backend_status,
    )
    backend_ok = source.index('$health.status -eq "ok"', backend_json)
    backend_success = source.index('$ready = $true', backend_ok)
    assert (
        '-UseBasicParsing -MaximumRedirection 0 -TimeoutSec 1'
        in source[backend_probe:backend_status]
    )
    assert backend_probe < backend_status < backend_json < backend_ok < backend_success

    frontend_probe = source.index(
        '$frontendResponse = Invoke-WebRequest -Uri "http://127.0.0.1:5173/"'
    )
    frontend_status = source.index(
        '$frontendResponse.StatusCode -eq 200', frontend_probe
    )
    frontend_success = source.index('$frontendReady = $true', frontend_status)
    assert (
        '-UseBasicParsing -MaximumRedirection 0 -TimeoutSec 1'
        in source[frontend_probe:frontend_status]
    )
    assert frontend_probe < frontend_status < frontend_success


def test_owned_process_rollback_waits_for_exit():
    """Static guard only: Windows end-to-end termination remains unverified."""
    source = LAUNCHER.read_text(encoding="utf-8")
    function = source.split("function Stop-OwnedProcess($Process) {", 1)[1].split(
        "\n}\n", 1
    )[0]
    refresh = function.index("$Process.Refresh()")
    kill = function.index("$Process.Kill()")
    wait = function.index("$Process.WaitForExit(5000)")
    timeout = function.index('Write-Warning "Owned process did not exit within 5 seconds;')
    assert refresh < kill < wait < timeout
    assert "Stop-Process -Name" not in function
