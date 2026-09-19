[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $root "Start-OrionTrader.cmd"
$icon = Join-Path $root "OrionTrader.ico"

if (-not (Test-Path $launcher)) {
    throw "Start-OrionTrader.cmd is missing from $root"
}

$shell = New-Object -ComObject WScript.Shell
$desktop = $shell.SpecialFolders.Item("Desktop")
$shortcutPath = Join-Path $desktop "OrionTrader.lnk"

# Recreate the shortcut instead of editing it in place. Explorer can otherwise
# keep the generic document icon cached from an older OrionTrader shortcut.
if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
}

$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Start the OrionTrader backend and frontend"
$shortcut.WindowStyle = 1
if (Test-Path $icon) {
    $shortcut.IconLocation = "$icon,0"
}
$shortcut.Save()

# Ask Explorer to refresh shell icons when Windows provides the cache refresh helper.
$iconRefresh = Join-Path $env:WINDIR "System32\\ie4uinit.exe"
if (Test-Path $iconRefresh) {
    Start-Process -FilePath $iconRefresh -ArgumentList "-show" -WindowStyle Hidden -ErrorAction SilentlyContinue
}

Write-Host "OrionTrader desktop shortcut created:" -ForegroundColor Green
Write-Host $shortcutPath
