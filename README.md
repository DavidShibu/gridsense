# GridSense - Team 3

EV charging and load-management demonstration using simulated sensors, MQTT,
Node-RED, SQLite, five ML models and actuator feedback.

For the configured **public internet MQTT broker**, follow [CLOUD_MQTT.md](CLOUD_MQTT.md).
On the project laptop run `./start.ps1 -PublicBroker`; on the sensor laptop run
`python simulator.py --public-broker`. Copy the four sensor Python files **plus
`mqtt-public.json`** to the sensor laptop. This uses `broker.emqx.io:8883` with
verified TLS and project-specific topics. No account or password is required.
The LAN setup below remains available as an alternative.

## Architecture

The implementation follows the branching diagram in `refererncesss.png`:

```text
Sensor laptop: Python sensor/plant simulator
    -> ev/telemetry -> Project laptop: Aedes MQTT broker -> Node-RED
        -> live dashboard
        -> SQLite commit -> database read -> ML/evaluation -> decision
            -> ev/actuator -> same MQTT broker -> sensor laptop actuator
                -> ev/ack -> MQTT -> Node-RED -> SQLite control metrics
```

The live dashboard and database are parallel outputs. Analytics reads committed
records and does not depend on an open browser. The actuator runs inside the sensor
process; do not run `actuator.py` separately. Run only one live simulator per station.

## Install on the project laptop

Install Python 3.10+ and Node.js 20 or later. In the extracted `GridSense` folder:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-tested.txt
npm.cmd ci --prefix node-red
```

`requirements-tested.txt` records the Python versions used for the included models;
`requirements-station.txt` provides supported dependency ranges. If the exact tested
versions are unavailable for your Python/platform, install the ranged requirements
and retrain locally before using the model files. Temporarily rename `artifacts/bundle.pkl`
to `bundle.pkl.saved` before starting the service if a model-version mismatch prevents
startup; training creates a new compatible bundle. On Linux/macOS use
`.venv/bin/python`, `npm` and `source .venv/bin/activate`.

## Two-laptop demonstration

Both laptops must be on a trusted Wi-Fi/LAN that permits connections between devices.
Guest Wi-Fi may block this. On the Windows **project laptop**:

1. Run `ipconfig` and note the connected adapter's IPv4 address.
2. Stop any previous GridSense launcher, then run `./start.ps1 -RemoteSensor`.
3. Allow TCP 1883 through Windows Firewall on the private network. If needed, run
   the following once in Administrator PowerShell:

```powershell
New-NetFirewallRule -DisplayName "GridSense MQTT LAN" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 1883 -Profile Private -RemoteAddress LocalSubnet
```

The launcher starts Aedes on all IPv4 interfaces and skips the local simulator.
An already-running broker must separately accept LAN connections. The demo broker
has no authentication/TLS; do not expose it to the internet.

On the **sensor laptop**, copy `simulator.py`, `actuator.py`, `station_core.py` and
`tariff.py` into one folder, then run:

```bash
python -m pip install "paho-mqtt>=2.1,<3"
python simulator.py --broker-host 192.168.1.10
```

Replace the example IP with the project laptop's address. Use `python3` where needed.
Add `--tou-demo` for the feasible evening tariff demonstration. The sensor laptop
needs neither Node-RED nor ML dependencies. Keep both laptop clocks synchronized
for meaningful sensor-to-actuator latency measurements.

Open on the project laptop:

- Dashboard: `http://127.0.0.1:1880/dashboard/station`
- Flow editor: `http://127.0.0.1:1880`

Changing dashboard readings demonstrate incoming telemetry. Accepted `ev/ack`
messages in Node-RED's debug sidebar demonstrate the return control path. A Windows
sensor laptop can check reachability with `Test-NetConnection 192.168.1.10 -Port 1883`.
Press Ctrl+C in each launcher/simulator terminal to stop.

## Single-laptop demonstration

On Windows run `./start.ps1` or `./start.ps1 -TouDemo`.
On Linux/macOS activate the virtual environment, start
`node node-red/demo-broker.cjs` in one terminal, and run `bash start.sh` in another.
The shell launcher is for a single laptop. For a Linux/macOS project host with a
remote sensor, run `node node-red/demo-broker.cjs --lan`, `python station_service.py`
and `npm --prefix node-red start` in separate terminals; do not run a local simulator.

## Train or refresh models

The submission includes trained models and measured JSON reports. SQLite starts
empty on a fresh extraction; the application creates it automatically. To reproduce
training, keep the project services running and use another terminal:

```powershell
./.venv/Scripts/python.exe simulator.py --history
Invoke-RestMethod http://127.0.0.1:8765/health
# Wait until history_rows is 1008, then:
./.venv/Scripts/python.exe ml_train.py
```

History replay can also run on the sensor laptop with `--broker-host <project-IP>`.
Restart the project services after training; model loading occurs once at startup.
If no model bundle exists, decisions explicitly report `untrained_safe_rules`.
Only load trusted model files. Training uses 28 days, validation seven days and
testing seven days of synthetic hourly observations stored in SQLite.

## Verification

```powershell
./.venv/Scripts/python.exe -m unittest discover -s tests -v
node node-red/validate-upgrades.cjs
```

For the full local MQTT integration check, first stop both laptops' demo processes
and free ports 1880/1883/8765, then run:

```powershell
./.venv/Scripts/python.exe tests/live_check.py
```

This starts a test stack, writes test rows into `station.db`, retrains models,
verifies storage and actuator feedback, refreshes `artifacts/live_check.json`,
and stops its processes. It does not test connectivity between physical laptops.
Offline comparisons: `python evaluate_control.py` and `python evaluate_tou.py`.

## Project files and submission

| File or directory | Purpose |
|---|---|
| `simulator.py`, `actuator.py`, `station_core.py` | Sensor/plant simulation and command application |
| `station_store.py`, `station_service.py` | Committed SQLite storage and local HTTP adapter |
| `ml_train.py`, `decision_engine.py` | Database-trained models and evaluated decisions |
| `tariff.py`, `tou_scheduler.py` | Simulated INR tariffs and constrained charging schedules |
| `node-red/` | MQTT flows, dashboard templates, broker and presentation builder |
| `tests/` | Behavior, architecture and integration checks |
| `artifacts/` | Trained models and measured evaluation reports |
| `GridSense_Final_Report.md` | Current methods, results and limitations |
| `GridSense_Presentation.pptx` | Presentation slides |

Rebuild slides with `node node-red/build-presentation.cjs`. Build the upload with
`python package_submission.py`. Upload **`submission/GridSense_Team3.zip` only**.
It contains source, dependency manifests, tests, documentation, models, metrics,
slides and SHA-256 checksums. It excludes local databases, installed dependencies,
logs, Git history and the local cleanup backup.

Sensor readings and tariffs are simulated. Real hardware requires a sensor/actuator
adapter; the demonstration does not establish real-world prediction accuracy.
