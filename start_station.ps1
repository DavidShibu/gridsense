param([switch]$TouDemo, [switch]$RemoteSensor, [switch]$CloudBroker, [switch]$PublicBroker)
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
$flowName = 'flows.json'
if ($PublicBroker) {
    & $nodePath 'node-red/build-public-flow.cjs'
    if ($LASTEXITCODE -ne 0) { throw 'Failed to generate public MQTT flow.' }
    $flowName = 'flows.public.json'
    $CloudBroker = $true
}
if ($CloudBroker) { $RemoteSensor = $true }
try {
    if (-not $CloudBroker) {
    $probe = [System.Net.Sockets.TcpClient]::new()
    try { $probe.Connect('127.0.0.1', 1883); $brokerReady = $true }
    catch { $brokerReady = $false }
    finally { $probe.Dispose() }
    if (-not $brokerReady) {
        $brokerArgs = if ($RemoteSensor) { "node-red/demo-broker.cjs --lan" } else { "node-red/demo-broker.cjs" }
        $workers += Start-Process $nodePath -ArgumentList $brokerArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "broker.log" -RedirectStandardError "broker.err.log"
    } elseif ($RemoteSensor) {
        Write-Warning "An existing broker is using port 1883. Ensure it accepts LAN connections; this launcher cannot change its listener."
    }
    }
    $workers += Start-Process $pythonPath -ArgumentList "station_service.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "service.log" -RedirectStandardError "service.err.log"
    $workers += Start-Process $nodePath -ArgumentList "node_modules/node-red/red.js --userDir . --settings settings.js $flowName" -WorkingDirectory "$PSScriptRoot/node-red" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot/nodered.log" -RedirectStandardError "$PSScriptRoot/nodered.err.log"
    Start-Sleep -Seconds 3
    if (-not $RemoteSensor) {
        $workers += Start-Process $pythonPath -ArgumentList $simulatorArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "station.log" -RedirectStandardError "station.err.log"
    } elseif ($PublicBroker) {
        Write-Host "On the sensor laptop: python simulator.py --public-broker (copy mqtt-public.json with the sensor files)."
    } elseif ($CloudBroker) {
        Write-Host "Cloud MQTT mode: configure the broker address, TLS and credentials in Node-RED. No local broker or sensor is started."
    } else {
        Write-Host "Waiting for the remote sensor. On the sensor laptop: python simulator.py --broker-host <this-laptop-LAN-IP>"
    }
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
