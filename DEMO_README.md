# GridSense - run the demonstration

This package contains only the files used to run the application and sensor demo.
The project laptop runs Node-RED, SQLite, ML and the dashboard. The sensor laptop
publishes simulated readings through `broker.emqx.io:8883` using verified TLS.

## 1. Set up sir's Windows laptop (once)

Install Python 3.10 or newer (Python 3.11 is supported) and Node.js 20 or later,
with both available on PATH. Setup installs compatible versions using
`requirements-station.txt`. Installing dependencies requires internet access.
The ZIP does not include Python, Node.js, a virtual environment or node_modules.

Extract the ZIP, open PowerShell in its `GridSense` folder, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_demo.ps1
```

This creates a local Python environment, installs compatible dependencies and
trains five demo models for that environment, preferring ACN data when configured. It does not modify your permanent
execution policy. Training may take a few minutes on a slower laptop.

Model preparation is an installation step: real-or-fallback history is staged
in a temporary SQLite database, then the models are trained from those records.
Only the resulting runtime bundle is kept. The live demo still uses the full
MQTT -> Node-RED -> SQLite -> ML/decision -> MQTT flow.

## 2. Start the project on sir's laptop

```powershell
powershell -ExecutionPolicy Bypass -File .\start_demo.ps1
```

Open **http://127.0.0.1:1880/dashboard/station** in the browser. Keep the PowerShell
window open. Do not run another copy of Node-RED or the project on ports 1880/8765.

## 3. Start the sensor

Copy the entire `sender` folder to the sensor laptop. It contains five runtime files, plus an optional prepared ACN fleet;
do not remove `station_core.py` or `tariff.py` from the project laptop because
the decision engine also imports them.

Open a terminal inside the copied `sender` folder and run:

```bash
python -m pip install "paho-mqtt>=2.1,<3"
python simulator.py --public-broker --tou-demo
```

The evening scenario demonstrates tariff-aware charging. Omit `--tou-demo` for
the default congested scenario. Both laptops need internet, but may use different
Wi-Fi networks. Keep the same `mqtt-public.json` on both sides. No account, MQTT
password, manual Node-RED configuration or router port forwarding is required.

For a one-laptop demonstration, keep `start_demo.ps1` running and open a second
PowerShell window in `GridSense`:

```powershell
.\.venv\Scripts\python.exe sender\simulator.py --public-broker --tou-demo
```

Even in this mode, messages travel through the internet MQTT broker.

## 4. Check the result and stop

The dashboard shows incoming readings, model comparison and charging decisions.
Open http://127.0.0.1:1880 for the Node-RED editor; accepted acknowledgement
messages in its debug sidebar confirm the return control path. Press Ctrl+C in
both the project and sensor terminals when finished.

The live SQLite database is created automatically on first use. Setup creates
`artifacts/bundle.pkl` with the selected trained model and all five model-comparison
results. `artifacts/runtime.json` records the local dependency versions. No model
trained under another Python environment is shipped in the ZIP. To force fully
offline preparation, run `setup_demo.ps1 -SyntheticOnly`.

## Retraining

If you change Python or ML package versions, stop the project and rerun
`setup_demo.ps1` to rebuild a compatible bundle. For an explicit demonstration
of history ingestion through the broker, keep the project running.
In a second project terminal:

```powershell
.\.venv\Scripts\python.exe sender\simulator.py --public-broker --history
Invoke-RestMethod http://127.0.0.1:8765/health
# Wait until history_rows is 1008, then:
.\.venv\Scripts\python.exe ml_train.py
```

Restart `start_demo.ps1` after training. The history replay remains synthetic and
follows MQTT -> Node-RED -> SQLite before training reads the database.

## Troubleshooting and limits

- No readings: check both internet connections, sender output and outbound TCP 8883.
- Service exits: read `service.err.log` and `nodered.err.log` created in this folder.
- TLS errors: check system clock and certificate trust; do not disable verification.
- Use only one live sensor for the shared topic prefix. Synchronize laptop clocks
  for meaningful response-time measurements.
- The public broker is shared and may be unavailable. Topics are not private;
  only simulated data should be sent. TLS does not prevent others publishing to
  public topics. The demo controls simulated actuators, not physical equipment.

Tests, reports, slides, logs, backups, databases and development utilities are
intentionally omitted from this demo package.

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
