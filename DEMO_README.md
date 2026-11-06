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
trains five demo models for that environment. It does not modify your permanent
execution policy. Training may take a few minutes on a slower laptop.

Model preparation is an offline installation step: synthetic history is staged
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

Copy the entire `sender` folder to the sensor laptop. It contains five files;
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
trained under another Python environment is shipped in the ZIP.

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
