param([switch]$TouDemo)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path "node-red/node_modules/node-red/red.js")) {
    throw "Run npm.cmd install --prefix node-red first."
}
$pythonPath = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python).Source }
$simulatorArgs = if ($TouDemo) { "simulator.py --tou-demo" } else { "simulator.py" }
$nodePath = (Get-Command node).Source
$workers = @()
try {
    $probe = [System.Net.Sockets.TcpClient]::new()
    try { $probe.Connect('127.0.0.1', 1883); $brokerReady = $true }
    catch { $brokerReady = $false }
    finally { $probe.Dispose() }
    if (-not $brokerReady) {
        $workers += Start-Process $nodePath -ArgumentList "node-red/demo-broker.cjs" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "broker.log" -RedirectStandardError "broker.err.log"
    }
    $workers += Start-Process $pythonPath -ArgumentList "station_service.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "service.log" -RedirectStandardError "service.err.log"
    $workers += Start-Process $nodePath -ArgumentList "node_modules/node-red/red.js --userDir . --settings settings.js flows.json" -WorkingDirectory "$PSScriptRoot/node-red" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot/nodered.log" -RedirectStandardError "$PSScriptRoot/nodered.err.log"
    Start-Sleep -Seconds 3
    $workers += Start-Process $pythonPath -ArgumentList $simulatorArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "station.log" -RedirectStandardError "station.err.log"
    Write-Host "Dashboard: http://127.0.0.1:1880/dashboard/station"
    Write-Host "Node-RED editor: http://127.0.0.1:1880"
    Write-Host "Press Ctrl+C to stop this run."
    while ($true) {
        Start-Sleep -Seconds 2
        foreach ($worker in $workers) {
            $worker.Refresh()
            if ($worker.HasExited) { throw "A service exited. See *.err.log files." }
        }
    }
} finally {
    foreach ($worker in $workers) {
        if (-not $worker.HasExited) { Stop-Process -Id $worker.Id -ErrorAction SilentlyContinue }
    }
}
