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
./.venv/Scripts/python.exe -m pip install -r requirements-station.txt
npm.cmd ci --prefix node-red
```

`requirements-station.txt` uses compatible version ranges, including Python 3.11.
Run `python prepare_demo.py` once after installing dependencies to train a model
bundle compatible with that environment. This installation step stages real-or-
fallback history in a temporary SQLite database. The demo ZIP supplies
`setup_demo.ps1` to automate installation and preparation.

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

The demo setup trains locally compatible models; source evaluation reports remain outside the demo ZIP. SQLite starts
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

ACN session behavior is preferred; SoC, tariffs and actuation remain simulated.
Real hardware and real-world prediction accuracy remain unverified.

## Real data source (ACN-Data)

ACN-Data is the preferred source for historical charging behavior and replay fleets.
Register and retrieve an API token at [Caltech ACN-Data](https://ev.caltech.edu/dataset).
On the **project laptop only**, set `ACN_DATA_TOKEN` in the current terminal (enter
its value locally, never commit it or paste it into chat):

```powershell
$env:ACN_DATA_TOKEN = '<your API token>'
# With the project services already running:
.\.venv\Scripts\python.exe simulator.py --public-broker --history
Invoke-RestMethod http://127.0.0.1:8765/health
.\.venv\Scripts\python.exe ml_train.py
```

Restart the project after training. `/health` exposes `data_source`, `dataset`,
`history_rows` and `active_history_rows`. The model report and dashboard also show
`data_source`. `ml_train.py --dataset acn-caltech-v1` explicitly selects real data;
otherwise training selects the most recently ingested dataset without mixing sources.

The adapter uses `acnportal.acndata.DataClient(token).get_sessions(...)` from the
published 0.3.3 release (`acnportal>=0.3.3,<0.4`). Session queries use bounded date
windows and time series. It discovers the latest available date rather than assuming
that data extends to today; optionally set `ACN_DATA_END=2020-02-12` to select a
specific exclusive end date (site-local midnight). The default site is Caltech;
`acn_data.fetch_sessions` also accepts `jpl` and `office001` for explicit use.

Fetched sessions are cached locally in `artifacts/acn_cache.json` for 24 hours,
keyed by site/start/end. Calls have HTTP timeouts and a bounded 300-second/5,000-session
fetch budget; incomplete downloads are rejected instead of reported as complete data.
The most recent incomplete site-local day is excluded. At least 18 days with observed
sessions are required; missing arrival hours within the fetched interval are zeros.
Each session's total delivered energy is assigned to its arrival-hour bin: this is
arrival-associated energy demand, **not** the measured power consumed in that hour.

If the token is missing, access fails, or data is insufficient, `[FALLBACK] Using
synthetic history` is logged. The unchanged deterministic generator is used and
reported as `synthetic-fallback`; prediction validity is limited to the simulation.
The service logs the fallback when that history reaches SQLite. To force offline data:

```powershell
.\.venv\Scripts\python.exe simulator.py --public-broker --history --synthetic-only
```

A successful project-laptop history replay also prepares `sender/acn_vehicles.json`.
Copy that file alongside the five sender files to **your sensor laptop**, then run
`python simulator.py --public-broker`. This file contains at most six derived vehicle
records from the latest session day, not raw current traces or credentials. The sensor
still installs **only paho-mqtt**. ACNPortal and requests remain project-laptop
requirements. If no prepared fleet is available, the standalone sensor explicitly
falls back. `--synthetic-only` bypasses even the prepared fleet. `--tou-demo` remains
the deliberately synthetic tariff scenario.

ACN-Data normally does not contain measured SoC or a vehicle make/model/year.
SoC is model-derived from native current timestamps, recorded session energy and
an assumed/known capacity. OpenEV's documented API requires hosting; the adapter
uses the project's public JSON release (discovered through its GitHub releases API)
when vehicle identity is supplied. Unknown/unavailable/ambiguous capacity uses a
logged **40 kWh assumption**, not an assertion about the actual car. Lookups are
cached in memory. See [OpenEV data consumption](https://open-ev-data.github.io/latest/dataset/HOW_TO_CONSUME/).

Current, voltage and efficiency determine trajectory shape; the trace is normalized
to `kWhDelivered`, so the energy-to-SoC convention matches the requested model.
Requested energy is preferred for initial-SoC inference; observed taper permits an
explicit 95%-final-SoC assumption, otherwise the supplied/default 30% initial SoC is
used. SoC is bounded to [0,1], with excess unrepresentable energy reported separately.
This is a calibrated simulation, not measured battery energy or a BMS model. Current
power and real SoC are not identified from session energy alone. Overnight departures
retain their duration; live actuation uses the existing piecewise taper model.

Tokens are read from the environment (or an explicit in-memory API argument), never
logged or written to cache. The submission ZIP excludes `.env*`, downloaded sessions,
ACN caches, and prepared fleets. Only aggregate energy/derived fleet data crosses
MQTT; do not add personal data to public broker messages.

## Saved ACN downloads and offline reuse

Download incrementally on the project laptop after setting ACN_DATA_TOKEN:

```powershell
.\.venv\Scripts\python.exe acn_data.py --download --seconds 120
```

Sessions are saved after every response in `data/acn_downloads/caltech-YYYY-MM-DD.json`.
Run the same command again to resume incomplete pages and skip completed days. The
seconds limit is checked between requests; an in-flight request can take additional
time. Each file records whether the whole day was downloaded. Credentials and user
identity fields are excluded. These durable historical snapshots do not expire like
the separate 24-hour API cache; rerunning the downloader extends the saved snapshot.

The root simulator automatically prefers this folder, with no token or network
needed to read it. Live mode can use valid sessions from a partial day. History mode
requires at least 18 observed days within a contiguous, completely downloaded
interval. Partial or missing days are never converted to zero-demand training rows.
Insufficient saved history logs a warning and uses synthetic fallback immediately.
A live ACN fleet therefore does not imply the ML training data is also ACN; check the
model report and /health separately. `--synthetic-only` bypasses saved data too.

The downloader also writes `sender/acn_vehicles.json` when usable vehicles exist.
Include that file when manually sending the sender folder. The standalone sender
can replay it with only paho-mqtt installed. Raw downloaded sessions remain on the
project laptop and are excluded from Git and the submission ZIP. The ZIP includes
the downloader code; download there or copy the data folder separately if needed.
