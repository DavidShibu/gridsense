$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path 'node-red/node_modules/node-red/red.js')) {
    throw 'Run ./setup_demo.ps1 first.'
}
$nodePath = (Get-Command node).Source
& $nodePath 'node-red/build-public-flow.cjs'
if ($LASTEXITCODE -ne 0) { throw 'Public MQTT flow generation failed.' }
$workers = @()
try {
    $workers += Start-Process $pythonPath -ArgumentList 'station_service.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'service.log' -RedirectStandardError 'service.err.log'
    $workers += Start-Process $nodePath -ArgumentList 'node_modules/node-red/red.js --userDir . --settings settings.js flows.public.json' -WorkingDirectory "$PSScriptRoot/node-red" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot/nodered.log" -RedirectStandardError "$PSScriptRoot/nodered.err.log"
    Write-Host 'Dashboard: http://127.0.0.1:1880/dashboard/station'
    Write-Host 'On the sensor laptop, inside sender/: python simulator.py --public-broker'
    Write-Host 'Keep this window open. Press Ctrl+C to stop.'
    while ($true) {
        Start-Sleep -Seconds 2
        foreach ($worker in $workers) {
            $worker.Refresh()
            if ($worker.HasExited) { throw 'A service exited. Check service.err.log and nodered.err.log.' }
        }
    }
} finally {
    foreach ($worker in $workers) {
        if (-not $worker.HasExited) { Stop-Process -Id $worker.Id -ErrorAction SilentlyContinue }
    }
}
