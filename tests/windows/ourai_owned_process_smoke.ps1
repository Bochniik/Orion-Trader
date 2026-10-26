# Windows-only smoke test for the REAL opt-in launcher ownership helpers.
# This does not start Orion/OurAI or touch journals, model files, or trading.
# It exercises Get-NetTCPConnection and process termination on a real Windows host.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$launcher = Join-Path $root "start-orion.ps1"

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $launcher, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "Launcher PowerShell parse failed: $($parseErrors[0].Message)"
}

# Import ONLY the function definitions from the launcher AST. Dot-sourcing
# start-orion.ps1 itself would install packages and start actual services.
foreach ($functionName in @("Assert-OwnedListener", "Stop-OwnedProcess", "Wait-ManagedProcesses")) {
    $definitions = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true))
    if ($definitions.Count -ne 1) {
        throw "Expected exactly one launcher definition of $functionName."
    }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Parse("127.0.0.1"), 0
)
$child = $null
try {
    $listener.Start()
    $port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $owner = Get-Process -Id $PID

    # TCP state publication can lag the listener.Start() call briefly.
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            Assert-OwnedListener $port $owner "owned test listener"
            $ready = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $ready) { throw "Real Windows loopback listener ownership check failed." }

    # A separate process cannot claim a listener belonging to this test.
    $child = Start-Process -FilePath (Join-Path $PSHOME "powershell.exe") `
        -ArgumentList @("-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 60") `
        -WindowStyle Hidden -PassThru
    $rejected = $false
    try {
        Assert-OwnedListener $port $child "unrelated test process"
    }
    catch {
        if ($_.Exception.Message -notmatch "does not own the expected loopback listener") {
            throw
        }
        $rejected = $true
    }
    if (-not $rejected) { throw "Unrelated process was accepted as listener owner." }

    # Rollback must terminate ONLY the process explicitly passed to it.
    Stop-OwnedProcess $child
    $child.Refresh()
    if (-not $child.HasExited) { throw "Owned child did not exit after rollback." }
    Assert-OwnedListener $port $owner "still-owned test listener"
    # A supervised launcher must notice an owned child exiting without
    # interfering with an unrelated existing loopback listener.
    $shortLived = Start-Process -FilePath (Join-Path $PSHOME "powershell.exe") `
        -ArgumentList @("-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Milliseconds 200") `
        -WindowStyle Hidden -PassThru
    try {
        $reason = Wait-ManagedProcesses @(@{ Name = "test child"; Process = $shortLived })
        if ($reason -ne "test child") { throw "Managed process exit was not detected." }
        Assert-OwnedListener $port $owner "listener after managed child exit"
    }
    finally {
        Stop-OwnedProcess $shortLived
        $shortLived.Dispose()
    }
    Write-Host "PASS: Windows loopback PID ownership, rollback, and supervised exit."
}
finally {
    $listener.Stop()
    if ($null -ne $child) {
        $child.Refresh()
        if (-not $child.HasExited) {
            Stop-OwnedProcess $child
        }
        $child.Dispose()
    }
}
