# GridSense: Smart EV Charging and Load Management — updated rubric

> Subsequent corrections supersede the methods/results below: see `FIXES_REVIEW.md`. The current version uses independent classifiers, feasibility-aware EDF, startup-only loading and 9.5 kW operation. The congested run now completes 4/6 targets with zero rapid switches; energy fulfillment is 65.5%.

## Objective and architecture

The project demonstrates a physical sensor layer represented by a Python simulation, MQTT communication, independent Node-RED live-display and SQLite-storage branches, database-trained ML, performance-aware decisions, and MQTT actuator feedback. See `AUDIT_RUBRIC.md` for the full diagram and exact node configuration. The SQLite adapter is local HTTP; the model training process never reads Node-RED messages.

## Methods

Six synthetic EVs share two chargers and 10 kW of site capacity, including 1 kW of base load. Arrivals, battery SoC, target energy, availability and departures influence least-laxity scheduling. A forecast can accelerate charging before predicted high demand. Assignment dwell, socket preservation and a rate deadband reduce unnecessary changes; safety and departure/completion override holds.

Training compares a decision tree, random forest and three-hidden-layer ANN on identical chronological splits of 1,008 synthetic hourly observations stored in SQLite. The first 28 days train, the next seven validate/select, and the last seven measure test performance. The decision engine uses validation RMSE and inference latency, with a constant baseline fallback. Test scores are not used for selection.

## Evaluation

All three models report RMSE, MAE and R² for future hourly energy. Thresholding energy at 30 kWh produces a defined high-demand classification task evaluated with accuracy, precision, recall and F1. Computational results include training duration, warmed single-sample latency, peak traced allocations and serialized size. The memory metric does not include all process/native memory.

Live closed-loop metrics include deadline success, energy fulfillment, unmet energy, peak load, overload samples, timestamped sensor-to-actuator latency and switch counts. Null ratios before any departure are explicitly displayed. Offline comparisons use the same initial state and step count for all model policies and a baseline.

## Results and limitations

Measured results are supplied as JSON under `artifacts/`. The first updated integration run confirmed 1,008 database rows, all three models trained, five accepted actuator commands, persisted acknowledgements, changed charging telemetry, dashboard HTTP 200 and a maximum observed load of 10 kW. Decision tree was selected on validation performance; a different model can have a lower test RMSE without changing that selection.

The congested original scenario achieves about 73.1% energy fulfillment with no fully met vehicle targets; the smaller-request scenario achieves 100% target completion. Both benchmarks observed zero capacity violations and zero rapid socket switches. No control-outcome improvement from ML over the constant baseline is established by these two scenarios. This limitation is part of the result, not a reason to suppress metrics.

Data and history are synthetic, connector reassignment is instantaneous, battery taper is simplified, and the scheduling heuristic has no optimality guarantee. Faculty approval remains external. Live network timing was measured on one host; multiple hosts require clock synchronization. Dashboard appearance and presentation layout require a final visual review.

## Reproduction and viva

Follow README setup and training commands. Explain why SQLite commit precedes inference, why the dashboard can keep updating when analytics fails, why regression/classification metrics differ, how validation differs from test, and how the actuator prevents replay and overload. Change a capacity/deadline and explain feasibility, or stop the service and demonstrate command expiry.
