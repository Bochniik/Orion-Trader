@echo off
setlocal
set "ORION_ROOT=%~dp0"
set "ORION_FAST_START="

if exist "%ORION_ROOT%.venv\Scripts\python.exe" if exist "%ORION_ROOT%frontend\node_modules\.bin\vite.cmd" set "ORION_FAST_START=-SkipInstall"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ORION_ROOT%start-orion.ps1" %ORION_FAST_START%
if errorlevel 1 (
  echo.
  echo OrionTrader could not start. Review the message above, then press any key.
  pause >nul
)
