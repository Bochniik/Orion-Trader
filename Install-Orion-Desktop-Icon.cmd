@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-orion-shortcut.ps1"
if errorlevel 1 (
  echo.
  echo The OrionTrader shortcut could not be created.
)
echo.
pause
