# GridSense: dashboard, five models and tariff-aware charging

The implementation is already in this workspace. MQTT topics remain `ev/telemetry`,
`ev/actuator` and `ev/ack`. SQLite tables and existing rows are preserved. New tariff
fields live in the existing telemetry/decision JSON columns; no migration is needed.
The active simulator/service stack uses synthetic sessions. The legacy acnportal
files are not changed.

The modern Vue overview (`node-red/templates/station-overview.vue`) now includes:

- Live/stale telemetry status and an explicit last-update time.
- Circular 0–10 kW grid-load gauge, charging/queued counts, tariff and next-departure cards.
  The gauge is green below 7 kW, yellow from 7 through 9.5 kW, and red above 9.5 kW
  (including 10 kW). Its ring saturates at 10 kW while the numeric reading continues
  to show overloads. Missing/invalid readings show an unavailable state.
- Vehicle search and All / On site / Waiting / Complete / Departed filters.
- Battery target markers, readable statuses and a fleet layout that becomes cards on mobile.
- Prominent station alerts above energy charts, with no green success message on stale analytics.
- A tariff-chart selector for the last 2, 6 or 12 simulated hours.
- Friendly model names, a selected-model badge and expandable metric explanations.

The visual system uses a deep green header, pale green page background, white panels,
consistent spacing, visible keyboard focus and reduced-motion support. It uses local
Vue templates and CSS with no external fonts or CDN scripts. Regenerate with
`python upgrade_dashboard.py` after editing templates, then restart Node-RED to load
the generated flow. The refresh preserves the existing MQTT and SQLite paths.

**1. Install dependencies and prepare the flow**

Stop your running launcher with Ctrl+C before restarting Node-RED. From the project root:

```powershell
uv pip install --python .venv/Scripts/python.exe -r requirements-station.txt
# Alternatively, in a Python environment with pip:
# python -m pip install -r requirements-station.txt
npm.cmd install --prefix node-red
.venv/Scripts/python.exe upgrade_dashboard.py
```

The last command is idempotent and has already been run. The original flow is saved
as `node-red/flows.before-upgrades.json`. The generated `node-red/flows.json` is the
complete flow, including the existing storage and actuator paths. Do not import it
as a second copy alongside the current flow. The launcher loads it on restart.

This project uses **FlowFuse Dashboard 2**, installed version 1.34.1. Its node names
are `ui-progress`, `ui-chart` and `ui-template`, with hyphens. Its templates use Vue;
legacy `ui_template` Angular snippets are not compatible. See the
[template documentation](https://dashboard.flowfuse.com/nodes/widgets/ui-template.html).

**2. Train and select all five models**

Full updated code: `ml_train.py`. Models are:

| Row | Regression estimator | Companion classifier for Accuracy |
|---|---|---|
| traditional_decision_tree | DecisionTreeRegressor | DecisionTreeClassifier |
| ensemble_random_forest | RandomForestRegressor | RandomForestClassifier |
| deep_ann | Scaled MLPRegressor, 64/32/16 | Scaled MLPClassifier |
| traditional_svr | Scaled RBF SVR | Scaled probabilistic SVC |
| ensemble_xgboost | XGBRegressor | XGBClassifier |

The two additions use this pattern (full hyperparameters are in the file):

```python
from sklearn.svm import SVR, SVC
from xgboost import XGBRegressor, XGBClassifier

svr = TransformedTargetRegressor(
    regressor=make_pipeline(StandardScaler(), SVR(C=10., epsilon=.1)),
    transformer=StandardScaler())
svc = make_pipeline(StandardScaler(), SVC(
    C=10., probability=True, class_weight='balanced', random_state=42))
xgb = XGBRegressor(objective='reg:squarederror', n_estimators=120,
                   max_depth=3, learning_rate=.05, tree_method='hist',
                   n_jobs=1, random_state=42)
```

XGBoost uses its [scikit-learn estimator interface](https://xgboost.readthedocs.io/en/stable/python/python_api.html).
Training reads only committed `demand_samples` from SQLite. The chronological split
is unchanged: first two thirds of days train, next sixth validate, last sixth test.
Scalers and class balancing use only training data. Accuracy refers to classifying
hourly demand >=30 kWh; it is not a regression accuracy percentage.

Automatic selection, run after each training:

```python
eligible = [name for name, m in comparisons.items()
            if m['computational']['inference_p95_ms'] <= 100
            and m['validation']['rmse_kwh'] <= baseline_val['rmse_kwh']]
selected = min(eligible, key=lambda n: comparisons[n]['validation']['rmse_kwh']) \
    if eligible else 'constant_baseline'
```

The table iterates over all report rows, displays Accuracy, RMSE, MAE, R² and p95,
and highlights the selected model. p95 measures 50 warmed, serial, single-sample
regressor predictions, including preprocessing. It excludes network and scheduling
time. Test scores never choose the winning model.

If SQLite already contains the 1008 historical rows, run:

```powershell
.venv/Scripts/python.exe ml_train.py
```

Otherwise start the stack, then in a second terminal:

```powershell
.venv/Scripts/python.exe simulator.py --history
Invoke-RestMethod http://127.0.0.1:8765/health
# Wait until history_rows is 1008, then:
.venv/Scripts/python.exe ml_train.py
```

The winner is written atomically to `artifacts/bundle.pkl`. Restart the service after
training: its existing cache intentionally loads models once per process. Selection
is automatic per training run, not continuous online retraining. No model is hard-coded.
The verified five-model candidate from this implementation is in `artifacts/upgrades/`;
normal training above publishes to the live artifact location.

**3. Configure the SoC progress bars**

The existing MQTT Input remains broker `127.0.0.1:1883`, topic `ev/telemetry`, QoS 1,
output parsed JSON. `live-filter` excludes history messages and fans out to:

```text
live-filter ──┬─ live-dashboard
              ├─ soc-router ── six ui-progress nodes
              ├─ load-series ── Grid Load over Time
              └─ price-history ── price-load-chart
```

| Node/property | Configuration |
|---|---|
| soc-router | Function, six outputs, one per EV1–EV6 |
| Each progress node | `ui-progress`, group `EV State of Charge` |
| Widget size | 6 columns × 1 row |
| Input | Numeric `msg.payload` from 0 to 100 |
| Dynamic label | `msg.ui_update.label`: EV, status, target |
| Dynamic color | Blue charging, green target reached, amber waiting |

Representative output for one EV:

```javascript
return {
  payload: Math.max(0, Math.min(100, ev.soc * 100)),
  ui_update: {
    label: `${ev.id} · ${ev.status} · target ${(ev.target*100).toFixed(0)}%`,
    color: ev.soc >= ev.target - 0.001 ? '#16a34a' : '#2563eb'
  }
};
```

The real Function routes by EV ID, never array position. An absent EV is explicitly
labelled unavailable with a grey bar. Add outputs/widgets and extend the ID list if
the fleet grows beyond these six IDs. Progress uses the
[Dashboard numeric percentage contract](https://dashboard.flowfuse.com/nodes/widgets/ui-progress.html).

**4. Configure load charts and coloured alerts**

| Grid Load over Time property | Value |
|---|---|
| Type / group / size | `ui-chart` / Grid load and tariff / 12 × 6 |
| Chart / action | Line / append |
| Series | `msg.topic` |
| X property | key `x`, timescale, wall-clock time |
| Y property | key `y`, kW, minimum 0 |
| Retention | 12 minutes and at most 1080 points |
| Series labels | Measured grid load, Operating limit, Unmanaged demand estimate |

The Function emits messages such as:

```javascript
{ topic: 'Measured grid load',
  payload: { x: telemetry.timestamp * 1000, y: telemetry.load_kw } }
```

MQTT timestamps are seconds; the chart requires milliseconds. The Function suppresses
duplicate/out-of-order sequence numbers and clears the chart on a new run. These
mappings follow the [chart documentation](https://dashboard.flowfuse.com/nodes/widgets/ui-chart.html).
The unmanaged line is a demand envelope from currently available EVs, not proof of
counterfactual savings. Use the paired simulation in step 6 for that comparison.

The second chart is a group-scoped `ui-template`, width 12, automatic height. Its
complete Vue/SVG implementation is `node-red/templates/price-load.vue`; it uses no CDN.
It has independent left kW and right INR/kWh scales and a shared simulated-hour X axis.
The bounded `price-history` Function feeds the last 360 samples:

```javascript
{ payload: { points: [ { hour: 22, price: 3, load: 7 } ] } }
```

`charging_load_kw` excludes base load. The price uses simulation time, not the PC's
clock. The SVG is a real dual-axis chart; price is not multiplied to imitate kW.
History lives in Node-RED memory, resets per run/restart, and is not backfilled from SQLite.

For alerts, wire output 1 of `Validate service response` to `alerts-panel` alongside
the ML table. The node is `ui-template`, group-scoped, width 12, automatic height,
pass-through off, resend-on-refresh on. Paste/use `node-red/templates/alerts.vue`:

```html
<div v-for="(alert, i) in alerts" :key="i" :class="['gs-alert', alert.level]">
  <strong>{{ alert.level.toUpperCase() }}</strong> — {{ alert.text }}
</div>
```

The complete component maps cannot-meet/unmet/violation messages to red critical boxes,
other alerts to amber warnings, and no current scheduling alerts to a green success box.
It renders plain text with Vue escaping and warns when the analytics timestamp is older
than 10 seconds. This is a freshness indication, not a broker connection diagnostic.

**5. Understand and adjust tariff scheduling**

Full code: `tariff.py`, `tou_scheduler.py`, and the integration in `decision_engine.py`.
The illustrative INR/kWh tariff is:

| Simulated hour | INR/kWh |
|---|---:|
| 00:00–06:00 | 3 |
| 06:00–16:00 | 6 |
| 16:00–22:00 | 12 |
| 22:00–24:00 | 3 |

```python
HOURLY_PRICES = (3.,) * 6 + (6.,) * 10 + (12.,) * 6 + (3.,) * 2

def price_at(hour):
    return HOURLY_PRICES[math.floor(hour) % 24]
```

The scheduler uses SciPy's [mixed-integer optimizer](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html).
It minimizes predicted commanded-energy cost over known sessions, with an earlier-time
tie-breaker. It enforces:

- Each EV receives its remaining energy by departure, allowing a conservative taper bound.
- A vehicle uses at most its rated charging power and only while present.
- Combined commanded charging power plus base load stays within 95% of site rating.
- Simultaneously assigned EVs never exceed the physical socket count.

The first interval is two simulated minutes, matching the simulator. Later slots are
at most 15 minutes, split at arrivals, departures and hourly tariff boundaries after
that first interval. Only the first action is applied; the next committed telemetry
snapshot causes a replan. Departures within the next control interval are handled
conservatively by falling back if the plan cannot be certified.

The decision integration is:

```python
plan = apply_tou(state, plan, previous, enabled=tou_enabled)
if plan['tou_status'] in ('disabled', 'fallback_edf'):
    plan = stabilize(state, plan, previous)
```

Do not run the old `stabilize()` after a successful ToU plan: it reallocates full power
and would cancel deliberate waiting. ToU retains existing socket assignments where
possible, but the old six-minute dwell/deadband does not constrain certified ToU plans.
The plant's independent capacity check and command watchdog still operate.

Strict deadlines are hard constraints **when feasible under the planning model**.
They cannot be guaranteed for overload, missing future arrivals, outages, changing
base load, or unknown battery behavior. Current base load is assumed constant over
the horizon; known future sessions are included. Targets near 100% may fail the
conservative taper check. Solver budget is 0.5 seconds; validated feasible incumbents
are usable even if optimization times out. Otherwise the existing EDF policy runs
with an explicit alert. Fallback is best effort, not a deadline guarantee.

Forecasting still produces the next-hour demand estimate and model comparison.
The ToU optimizer uses known session energy requirements for deadline constraints;
it does not treat the aggregate ML energy forecast as a vehicle-level guarantee.

**6. Run, demonstrate and verify**

After training, stop any old launcher and start the tariff demonstration:

```powershell
.\start_station.ps1 -TouDemo
```

Open `http://127.0.0.1:1880/dashboard/station`. The demo begins at simulated 16:00:
EV1 needs 4 kWh by 18:00, EV2 needs 12 kWh by midnight. EV1 charges despite high price;
EV2 can wait until the 22:00 price drop. One simulated hour takes about one real minute.
Other EV bars show unavailable. Use `./start_station.ps1` for the original six-EV demo;
that deliberately overloaded scenario may produce fallback and unmet-demand alerts.

Run the checks without starting another live stack:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
node node-red/validate-upgrades.cjs
.venv/Scripts/python.exe evaluate_tou.py
```

The paired simulation saves full traces to `artifacts/tou_comparison.json`. Verified
results on the feasible demonstration (same 16 kWh delivered, all deadlines met):

| Policy | EV energy cost (INR) | Peak grid load (kW) |
|---|---:|---:|
| Unmanaged counterfactual | 192 | 15 |
| Existing capacity-limited EDF | 192 | 9.5 |
| ToU | 84 | 8 |

These are synthetic scenario results, not a general savings guarantee. Base-load
energy is excluded from every cost figure. The unmanaged reference removes the site
power limit for comparison and must not be sent to a real actuator.

Validation covers five-model training, chronological selection, deadline priority,
socket competition, future arrivals, infeasibility, tariff wraparound, and paired
cost/peak results. JavaScript checks compile the Vue templates and exercise actual
flow Functions. Browser appearance still needs a visual check after restarting.

For the full MQTT/SQLite integration test, stop the application first so ports
1880/1883/8765 are free, then run `python tests/live_check.py`. It trains/publishes
live artifacts and appends test runs to the existing SQLite database.
