#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python station_service.py > service.log 2>&1 & service_pid=$!
(cd node-red && exec node node_modules/node-red/red.js --userDir . --settings settings.js flows.json) > nodered.log 2>&1 & red_pid=$!
python simulator.py > station.log 2>&1 & simulator_pid=$!
trap 'kill "$service_pid" "$red_pid" "$simulator_pid" 2>/dev/null || true' EXIT INT TERM
echo "Dashboard: http://127.0.0.1:1880/dashboard/station"
wait -n
