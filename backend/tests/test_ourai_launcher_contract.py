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
    readiness = source.index('$evidence = Invoke-RestMethod')
    checks = source.index('$evidence.journal_valid -eq $true')
    failure = source.index('throw "OurAI bridge did not return verified read-only evidence.')
    enable = source.index('$env:OURAI_BRIDGE_ENABLED = "true"')
    backend_start = source.index('$backendProcess = Start-Process')
    assert readiness < checks < failure < enable < backend_start
    assert '$evidence.trading_enabled -eq $false' in source
    assert '$evidence.direction_available -eq $false' in source
    assert 'Stop-Process -Id $ouraiProcess.Id' in source


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
    assert launch_section.count(cleanup) == 2
    assert launch_section.count('Stop-Process -Id $ownedProcess.Id') == 2
    assert 'if ($StartOurAI) {' in launch_section
    assert 'throw "Orion backend did not become ready;' in launch_section
    assert 'Write-Warning "The backend did not become ready in time.' in launch_section
    assert 'Stop-Process -Name' not in source
    assert 'Get-Process | Stop-Process' not in source
