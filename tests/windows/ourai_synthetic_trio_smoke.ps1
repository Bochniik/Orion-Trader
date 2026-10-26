# Windows-only synthetic local-process integration smoke.
# No OurAI/Orion runtime, forward journal, model, data, credentials, or orders.
# Three disposable PowerShell children provide minimal TCP services on loopback.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $root "start-orion.ps1"), [ref]$null, [ref]$null
)
foreach ($functionName in @("Assert-OwnedListener", "Stop-OwnedProcess", "Wait-ManagedProcesses")) {
    $definitions = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true))
    if ($definitions.Count -ne 1) {
        throw "Expected exactly one $functionName function in launcher."
    }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}

function Get-FreeLoopbackPort {
    $socket = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback, 0
    )
    try {
        $socket.Start()
        return ([System.Net.IPEndPoint]$socket.LocalEndpoint).Port
    }
    finally { $socket.Stop() }
}

function Assert-SyntheticTcpResponse([int]$Port) {
    $socket = [System.Net.Sockets.TcpClient]::new()
    try {
        $socket.Connect("127.0.0.1", $Port)
        $stream = $socket.GetStream()
        $stream.WriteByte(42)
        if ($stream.ReadByte() -ne 79) {
            throw "Synthetic loopback service on port $Port did not respond."
        }
    }
    finally { $socket.Dispose() }
}

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("orion-trio-" + [guid]::NewGuid().ToString("N"))
$children = @()
$unrelated = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback, 0
)
try {
    [void](New-Item -ItemType Directory -Path $temp)
    $worker = Join-Path $temp "synthetic-loopback-worker.ps1"
    @'
param([int]$Port)
$ErrorActionPreference = "Stop"
$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback, $Port
)
try {
    $listener.Start()
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            $stream = $client.GetStream()
            if ($stream.ReadByte() -eq 42) {
                $stream.WriteByte(79)
            }
        }
        finally { $client.Dispose() }
    }
}
finally { $listener.Stop() }
'@ | Set-Content -LiteralPath $worker -Encoding UTF8

    $unrelated.Start()
    $unrelatedPort = ([System.Net.IPEndPoint]$unrelated.LocalEndpoint).Port
    $ownProcess = Get-Process -Id $PID
    Assert-OwnedListener $unrelatedPort $ownProcess "unrelated listener"

    $ports = @()
    foreach ($service in @("OurAI synthetic", "Orion backend synthetic", "Orion frontend synthetic")) {
        $port = Get-FreeLoopbackPort
        if ($port -eq $unrelatedPort -or $ports -contains $port) {
            throw "Synthetic test port collision."
        }
        $ports += $port
        # Never launch code from the repo's real OurAI or Orion application.
        $child = Start-Process -FilePath (Join-Path $PSHOME "powershell.exe") `
            -ArgumentList @("-NoProfile", "-NonInteractive", "-File", "`"$worker`"", "-Port", "$port") `
            -WindowStyle Hidden -PassThru
        $children += @{ Name = $service; Process = $child; Port = $port }
    }

    foreach ($entry in $children) {
        $ready = $false
        for ($attempt = 0; $attempt -lt 50; $attempt++) {
            try {
                Assert-OwnedListener $entry.Port $entry.Process $entry.Name
                Assert-SyntheticTcpResponse $entry.Port
                $ready = $true
                break
            }
            catch {
                $entry.Process.Refresh()
                if ($entry.Process.HasExited) { throw }
                Start-Sleep -Milliseconds 100
            }
        }
        if (-not $ready) { throw "$($entry.Name) never became a valid owned loopback service." }
    }

    # Simulate failure of one of three owned services and detect it.
    Stop-OwnedProcess $children[1].Process
    $reason = Wait-ManagedProcesses @(
        $children | ForEach-Object { @{ Name = $_.Name; Process = $_.Process } }
    )
    if ($reason -ne "Orion backend synthetic") {
        throw "Supervisor failed to identify the exited synthetic backend."
    }

    # Mirroring the launcher's finally block must spare unrelated processes.
    foreach ($entry in $children) { Stop-OwnedProcess $entry.Process }
    foreach ($entry in $children) {
        $entry.Process.Refresh()
        if (-not $entry.Process.HasExited) { throw "Owned $($entry.Name) survived rollback." }
        $listener = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $entry.Port `
            -State Listen -ErrorAction SilentlyContinue
        if ($listener) { throw "Synthetic port $($entry.Port) still has a listener." }
    }
    Assert-OwnedListener $unrelatedPort $ownProcess "unrelated listener after rollback"
    Write-Host "PASS: three owned loopback services, TCP probes, failure detection, scoped shutdown."
}
finally {
    foreach ($entry in $children) {
        Stop-OwnedProcess $entry.Process
        $entry.Process.Dispose()
    }
    $unrelated.Stop()
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
