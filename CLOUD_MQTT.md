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
or publish to these topics. Use synthetic data only. TLS verifies the server and
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
project launcher to load refreshed models. History is synthetic and is sent through
the same public broker. The submission already includes trained model artifacts.

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
