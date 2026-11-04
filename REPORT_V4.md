# GridSense: Smart EV Charging and Load Management

> Archived v4 report. The current rubric-compliant implementation is documented in `REPORT_V5.md` and `AUDIT_RUBRIC.md`.

## Problem and architecture

Several vehicles compete for limited charging sockets and electrical capacity. The implemented loop is Python simulation → MQTT broker → Node-RED → Python HTTP service with SQLite and analytics → Node-RED Dashboard → Node-RED MQTT publisher → simulated station actuator.

Node-RED owns message integration and command publication. The Python service is an analytics/persistence component invoked by Node-RED; it does not connect directly to MQTT. SQLite stores full snapshots and decisions, including source, run ID, arrival/departure, target, charger assignment, applied command sequence and remaining energy. The dashboard displays stored-cycle results. Actuator acknowledgements appear in the Node-RED debug panel; the next telemetry snapshot records the applied sequence.

## Data and simulation

Six explicitly synthetic EV profiles compete for two sockets. The electrical capacity is 10 kW, including a 1 kW non-EV load. Two real seconds correspond to two simulated minutes. Vehicles arrive at different times, queue, charge, complete or depart. Delivered energy is capped at the target and charging stops at departure. A simplified taper reduces accepted power above 80% SoC. No real ACN data or ACN-Sim library execution is claimed for this version.

## Analytics and decisions

A reproducible synthetic history contains 28 days of hourly energy requests with arrival peaks. A seasonal-mean regression learns each hour's mean demand on days 1–21. Days 22–28 provide held-out mean absolute error and a constant-mean baseline comparison. The dashboard displays both metrics and hourly arrival patterns. This is an educational forecast demonstration, not evidence of real station accuracy.

The scheduling heuristic ranks arrived vehicles by laxity: time until departure minus remaining energy divided by maximum charging power. It assigns available sockets, calculates deadline-based rates and allocates within the shared capacity. When next-hour forecast demand exceeds its historical mean, required rates increase by 25% where capacity permits. Impossible individual requests and aggregate energy shortfalls produce alerts. Deadlines remain explicit; a predicted completion time never replaces them.

## Control and reliability

One MQTT command contains the complete station allocation. The actuator validates all assignments before applying any, rejects duplicate or outdated sequences and wrong run IDs, and enforces capacity locally. Commands expire after six simulated minutes without renewal. MQTT QoS 1 permits redelivery; sequence checks and SQLite primary keys make repeated delivery safe. Physical connector switching and network security outside localhost are outside this simulation's scope.

## Validation

`python -m unittest discover -s tests -v` checks a full simulated scenario, power limits, queue behavior, departures, target limits, invalid command rejection, duplicate handling, command expiry, reduced capacity, no early arrivals, held-out forecast comparison and database idempotency. Live broker/Node-RED validation is a separate integration check and must not be inferred from offline test results.

## Evaluation readiness

Live smoke test completed on 3 November 2026 with Node-RED 4.1.17, Dashboard 2.0 1.34.1 and a local Aedes MQTT broker: three accepted commands, four persisted cycles, dashboard HTTP 200, and maximum observed load 10.0 kW. This verifies message routing, persistence and changed actuator telemetry. It does not constitute visual browser verification or a long-running reliability test.

Use the README demonstration sequence for viva and debugging. Explain the MQTT topics, database schema, deadline calculation, forecast baseline, simulated clock and command expiry. Change capacity or arrival times and explain the resulting queue. Meaningful advanced features include forecast-aware scheduling, infeasibility alerts, atomic station plans, replay rejection and a communication-loss timeout.

Faculty approval of the selected simulator/data source remains external and unverified. Submission is a ZIP via the faculty-provided form; no automatic submission occurs. Do not claim all EV targets can be met when the requests exceed physical capacity.
