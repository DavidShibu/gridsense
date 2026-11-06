# GridSense: Smart EV Charging and Load Management

Team 3 - Submission report

## Objective

Demonstrate a complete distributed IoT feedback loop for a simulated EV charging
station: sensor observations, MQTT transport, live visualization, persistent data,
evaluated machine learning, control decisions and actuator acknowledgements.

## Architecture and deployment

The supplied architecture image is `refererncesss.png`. One laptop runs the Python
sensor/plant simulator and attached actuator; the second runs Aedes on TCP 1883,
Node-RED, SQLite, the analytics/decision service and the dashboard. This describes
the retained local/LAN mode. The current public-broker mode instead connects both
laptops to `broker.emqx.io:8883` over verified TLS, using the shared prefix in
`mqtt-public.json`. No local MQTT broker is started in public mode.

1. `simulator.py` publishes JSON observations on `ev/telemetry` every two seconds.
2. Node-RED receives observations through MQTT with QoS 1.
3. Independent branches update the dashboard and POST observations to `/store`.
4. SQLite commits the observation and returns its run/sequence key. `/decide` reads
   the committed row, performs inference and builds a control plan.
5. Node-RED publishes that plan on `ev/actuator` through the same broker.
6. The sensor laptop validates and applies the plan and publishes `ev/ack`.
7. Node-RED stores acknowledgements for closed-loop evaluation. Subsequent readings
   reflect the action applied to the simulated plant.

The Python HTTP adapter is internal to the project laptop. MQTT connects the two
laptops; neither the dashboard nor database needs to be exposed to the LAN. The
live display continues independently when analytics is unavailable. The plant
rejects invalid, duplicate or out-of-order plans and expires stale commands.

## Simulation and scheduling

The station has six EVs, two charger sockets, a 10 kW rated supply and 1 kW base
load. A 5% reserve produces a 9.5 kW operating limit. Arrivals, departure deadlines,
remaining energy, battery state and charge-rate limits constrain scheduling.
The fallback scheduler uses feasibility-aware earliest departure priority, stable
socket assignments, dwell time and a power deadband. The tariff scheduler uses
constrained optimization to defer flexible demand while respecting deadlines;
solver failure falls back to deadline scheduling. Tariffs are illustrative INR/kWh.

The `--tou-demo` scenario provides feasible evening requests. The default congested
scenario deliberately includes demand that cannot all be served by its deadlines.

## Machine learning and evaluation

History replay sends 1,008 synthetic hourly records (42 days) through MQTT and
Node-RED to SQLite. Training selects database rows only. The chronological split
uses 28 training days, seven validation days and seven test days.

Five model families cover the three categories in the diagram:

- Traditional: decision tree and support vector regression/classification.
- Ensemble: random forest and XGBoost.
- Neural network: feed-forward ANN with hidden layers 64, 32 and 16.

Each family includes an energy regressor and an independently trained classifier
for high demand (at least 30 kWh per hour). Regression metrics are RMSE, MAE and R2;
classification metrics include accuracy, precision, recall and F1. Computational
metrics include training time, warmed inference latency, serialized size and peak
Python-tracked allocations. Tracked memory is not total process/GPU memory.

Selection uses validation RMSE subject to a 100 ms p95 inference limit and improvement
against the constant baseline. Test scores do not select models. The current selected
model is **traditional_decision_tree**. Models are loaded and warmed at service startup.
Without a bundle, the application explicitly reports `untrained_safe_rules`.

| Model | Test RMSE (kWh) | MAE (kWh) | R2 | Accuracy | F1 |
|---|---:|---:|---:|---:|---:|
| traditional_decision_tree | 13.155 | 10.399 | 0.532 | 0.917 | 0.788 |
| ensemble_random_forest | 12.824 | 10.193 | 0.555 | 0.893 | 0.757 |
| deep_ann | 13.007 | 10.214 | 0.543 | 0.851 | 0.706 |
| traditional_svr | 14.539 | 11.414 | 0.428 | 0.911 | 0.776 |
| ensemble_xgboost | 12.706 | 9.976 | 0.564 | 0.917 | 0.788 |

Exact metrics, splits and warnings are in `artifacts/ml_comparison.json`; held-out
predictions are in `artifacts/classification_predictions.json`.

## Verified results

The recorded local integration test (`artifacts/live_check.json`) verified:

- 1008 historical observations persisted through MQTT/Node-RED.
- 5 live cycles and 5 acknowledgements stored.
- 5 accepted commands and changed actuator telemetry.
- Dashboard HTTP status 200.
- Peak observed site load 9.5 kW.
- Mean sensor-to-actuator response 38.16 ms;
  p95 response 41.99 ms.

This is a short local-loop check, not a sustained or two-physical-laptop network
benchmark. Cross-laptop latency requires synchronized system clocks.

The offline fallback-policy comparison (`control_comparison.json`) meets four of
six congested targets, supplies 65.5% of requested energy and records zero capacity
violations or rapid switches. The feasible low-energy comparison
(`control_feasible.json`) meets all targets. These scenarios do not establish a
control-outcome advantage of ML over the constant baseline.

The separate evening tariff comparison (`tou_comparison.json`) delivers 16 kWh
and meets all deadlines. Deadline-only charging costs INR 192; tariff-aware charging
costs INR 84 (56.25% lower). Peak site demand is 9.5 kW and 8 kW respectively. This
result is specific to the synthetic scenario and illustrative prices. The unmanaged
counterfactual reaches 15 kW and intentionally has no site cap.

## Public-broker verification

A separate real-internet test is recorded in `artifacts/public_mqtt_check.json`.
It verified TLS, five accepted commands, six stored cycles and six stored
acknowledgements through `broker.emqx.io:8883`, with the trained decision-tree
model, dashboard HTTP 200 and a 9.5 kW observed peak. Mean observed response was
approximately 700 ms. Both test clients ran locally while using the real internet
broker; connectivity between the user's two physical laptops remains to be tested.

Public topics are not access-controlled. The unique namespace reduces collisions
but does not prevent others reading data or injecting messages. TLS protects the
connection, not topic privacy. Only synthetic demonstration data is used.

## Reproduction and limitations

Follow `README.md` for setup, the two-laptop commands, history replay, training and
verification. The test suite checks storage-before-inference, architecture wiring,
model selection, command rejection, safety limits, scheduling and tariff behavior.
`tests/live_check.py` runs the local broker/Node-RED/service/simulator loop.

The sensor and actuator are simulated, socket reassignment is instantaneous and
battery taper is simplified. The ANN is a multilayer feed-forward network, not an
LSTM. Real-world prediction accuracy and physical-hardware control are unverified.
The demo broker has no authentication or TLS and is intended for a trusted LAN.
Included pickle models must be trusted and used with compatible Python dependencies;
retrain if dependency versions differ. Actual grading/upload requirements remain
those of the receiving institution.
