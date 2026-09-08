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
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Start the OrionTrader backend and frontend"
$shortcut.WindowStyle = 1
if (Test-Path $icon) {
    $shortcut.IconLocation = "$icon,0"
}
$shortcut.Save()

Write-Host "OrionTrader desktop shortcut created:" -ForegroundColor Green
Write-Host $shortcutPath
