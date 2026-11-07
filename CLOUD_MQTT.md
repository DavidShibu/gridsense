# Two laptops through the public EMQX broker

## Ready-to-run configuration

The project is configured for **broker.emqx.io:8883**, using verified TLS and no
username/password. Only the broker is hosted on the internet; the project laptop
still runs Node-RED, SQLite, ML and the dashboard.

```text
Sensor laptop -> public EMQX broker -> project laptop
Sensor laptop <- public EMQX broker <- control commands
```

The shared `mqtt-public.json` selects these topics:

- `gridsense/team3/b7749f4efd894610/telemetry`
- `gridsense/team3/b7749f4efd894610/actuator`
- `gridsense/team3/b7749f4efd894610/ack`

Both laptops must have the same copy of that file. Unique topics reduce collisions;
they are not private or authenticated. Other public-broker users can read messages
or publish to these topics. Do not publish personal data; the ACN adapter sends only aggregate/derived demo data. TLS verifies the server and
encrypts transport; it does not restrict other clients' topic access. See the
[official public broker information](https://www.emqx.com/en/mqtt/public-mqtt5-broker).

## Project laptop (Windows)

Install dependencies using README if not already installed. Stop the previous
launcher, then run from the project folder:

```powershell
./start.ps1 -PublicBroker
```

This automatically generates `node-red/flows.public.json` with TLS, the broker
address, a unique client ID and the shared topics, then starts Node-RED and the
Python database/decision service. No local broker or sensor is started. No manual
Node-RED broker editing, cloud account or MQTT credentials are needed.

Open `http://127.0.0.1:1880/dashboard/station` for the dashboard and
`http://127.0.0.1:1880` for the editor. Keep this launcher running.

## Sensor laptop

Copy these **five current files** into one folder:

1. `simulator.py`
2. `actuator.py`
3. `station_core.py`
4. `tariff.py`
5. `mqtt-public.json`

Install Python 3.10+ and run in that folder:

```bash
python -m pip install "paho-mqtt>=2.1,<3"
python simulator.py --public-broker
```

Use `python3` if required by your OS. Add `--tou-demo` for the evening tariff demo.
The simulator prints the broker and topics when connected. Public mode does not
send private MQTT credentials even if MQTT_USERNAME/MQTT_PASSWORD are set.

Both laptops need internet access; they do not need the same Wi-Fi. No inbound
MQTT port or router port forwarding is required. Keep both clocks synchronized
for meaningful response-time measurements. Only run one live simulator for this
station. Stop the simulator and project launcher with Ctrl+C when finished.

## Verify the demonstration

1. The Node-RED MQTT nodes should show connected status.
2. Dashboard readings should update from the other laptop.
3. Accepted messages in the acknowledgement debug output confirm that decisions
   returned through MQTT and were applied by the sensor laptop.
4. Try the sensor laptop on another internet connection to demonstrate the split.

The project has already passed a real-broker integration test using local test
clients connected through `broker.emqx.io`, not a local broker. It verified five
accepted commands, persisted telemetry/acknowledgements and trained decisions.
See `artifacts/public_mqtt_check.json`. This is not a test of your two physical
laptops. Reproduce with `python tests/public_mqtt_check.py` after stopping the demo;
this uses separate temporary test topics and writes test cycles to `station.db`.

## History and model training

With the public-mode project launcher running, use this command on either laptop:

```bash
python simulator.py --public-broker --history
```

On the project laptop, wait until `http://127.0.0.1:8765/health` reports 1,008 history
rows, then run `python ml_train.py` using the project environment. Restart the
project launcher to load refreshed models. Run history replay from the project root to enable ACN fetching. It uses the
same public broker and explicitly labels real versus fallback data. Demo setup
trains local models; it does not ship cross-version model binaries.

## Other modes and troubleshooting

- `./start.ps1` keeps the original single-laptop local demo.
- `./start.ps1 -RemoteSensor` uses a local LAN broker as described in README.
- `./start.ps1 -CloudBroker` is for a private hosted broker configured manually in
  the original Node-RED flow; it does not select the public profile.
- Generated public-flow edits are replaced at startup. Make shared application
  changes in `node-red/flows.json` or the public-flow generator.
- For Linux/macOS project hosts, run `node node-red/build-public-flow.cjs`, start
  `python station_service.py`, and in another terminal run
  `node node-red/node_modules/node-red/red.js --userDir node-red --settings node-red/settings.js node-red/flows.public.json`.
- If connection fails, check internet access and outbound TCP 8883. The public broker
  is a shared test service; it may be unavailable. Certificate failures should be
  fixed by checking the clock/trust store, never by disabling verification.
- A private broker can use `python simulator.py --broker-host HOST --tls --username USER`;
  the password is prompted. Configure matching credentials, TLS and topics in Node-RED.

If another team uses this submission independently, choose a different unique
`topic_prefix` in `mqtt-public.json`, copy it to both laptops and restart both sides.

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
