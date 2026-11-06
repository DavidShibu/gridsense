param([switch]$TouDemo, [switch]$RemoteSensor, [switch]$CloudBroker, [switch]$PublicBroker)
& "$PSScriptRoot/start_station.ps1" -TouDemo:$TouDemo -RemoteSensor:$RemoteSensor -CloudBroker:$CloudBroker -PublicBroker:$PublicBroker
