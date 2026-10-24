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
