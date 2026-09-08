from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "start-orion.ps1"
DESKTOP_LAUNCHER = ROOT / "Start-OrionTrader.cmd"
SHORTCUT_INSTALLER = ROOT / "install-orion-shortcut.ps1"
SHORTCUT_ICON = ROOT / "OrionTrader.ico"


def test_windows_launcher_rejects_stale_service_ports_before_starting():
    script = LAUNCHER.read_text(encoding="utf-8")

    backend_check = script.index('Assert-PortAvailable 8000 "OrionTrader backend"')
    frontend_check = script.index('Assert-PortAvailable 5173 "OrionTrader frontend"')
    first_start = script.index('Start-Process -FilePath $venvPython')

    assert backend_check < first_start
    assert frontend_check < first_start
    assert "OwningProcess" in script


def test_windows_launcher_forces_the_documented_frontend_port():
    script = LAUNCHER.read_text(encoding="utf-8")

    assert '"--port", "5173"' in script
    assert '"--strictPort"' in script
    assert 'Start-Process "http://127.0.0.1:5173"' in script


def test_desktop_launcher_bypasses_policy_only_for_its_process_and_uses_fast_start():
    script = DESKTOP_LAUNCHER.read_text(encoding="utf-8")

    assert "-ExecutionPolicy Bypass" in script
    assert "start-orion.ps1" in script
    assert ".venv\\Scripts\\python.exe" in script
    assert "frontend\\node_modules\\.bin\\vite.cmd" in script
    assert "-SkipInstall" in script


def test_shortcut_installer_targets_the_project_launcher_on_the_desktop():
    script = SHORTCUT_INSTALLER.read_text(encoding="utf-8")

    assert 'SpecialFolders.Item("Desktop")' in script
    assert '"OrionTrader.lnk"' in script
    assert '"Start-OrionTrader.cmd"' in script
    assert "$shortcut.WorkingDirectory = $root" in script
    assert SHORTCUT_ICON.read_bytes()[:4] == b"\x00\x00\x01\x00"
