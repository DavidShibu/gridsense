# Verified dashboard corrections

## Findings before changes

`artifacts/diagnosis_before.json` records the checks. Original regressors made identical binary predictions at 30 kWh despite different numeric forecasts. All confusion matrices were TN=128, FP=2, FN=12, TP=26. The 168 test rows include 38 positives and 130 negatives; majority accuracy is 77.4%. Identical scores were legitimate, not copied or fabricated.

The original loader already cached artifacts but loaded/warmed on the first request. Saved model p95 times were 0.19, 4.89 and 0.44 ms. Dashboard response time measures the full loop, not just inference. The original least-laxity policy prioritized impossible jobs and had no capacity reserve.

## Changes

- Train independent tree, forest and ANN classifiers alongside regressors. Keep the 30 kWh target and 0.5 probability cutoff. Use balanced tree/forest weights and deterministic ANN training-only oversampling. Never rebalance or tune against the test set. Save confusion matrices, balanced accuracy, average precision and per-row predictions. Future models may still legitimately have identical scores.
- Use feasibility-aware EDF, giving still-feasible jobs earliest-departure priority and impossible jobs best effort. Allocate power to complete the earliest admitted deadline before later jobs.
- Load/warm saved models once before serving HTTP requests. Retraining now requires a service restart; no automatic reload occurs during inference.
- Enforce 95% of physical site capacity in scheduler AND actuator: 9.5 kW total, including 1 kW base load, leaves 8.5 kW for EVs.
- Preserve six-minute dwell, socket mapping and 0.25 kW deadband. Remove redistribution that could undo the deadband. Record inference/decision timing separately from full-loop response.

## Results

| Classifier | Accuracy | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| Tree | .917 | .929 | .684 | .788 |
| Forest | .893 | .778 | .737 | .757 |
| ANN | .851 | .638 | .789 | .706 |

These scores trade precision for recall; they were not forced to differ. Original congested scenario: 4/6 targets complete, 9.5 kW peak, zero rapid switches. Energy fulfillment falls from 73.1% to 65.5% because feasible completed requests take priority over spreading energy across all requests. Low-energy scenario: all six complete. Impossible requests still cannot be guaranteed (EV2 needs 16 kWh in two hours from a 7 kW charger).

Five-command local smoke test: mean response 48.4 ms, p95 73.4 ms, mean inference 0.58 ms. This is not a worst-case guarantee. Nineteen tests pass. The Node-RED flow and MQTT topics are unchanged.

## Activate

Stop the old launcher with Ctrl+C and run `./start.ps1` again. Source and artifacts are already updated. Do not start duplicate services. A new simulator run ID starts fresh displayed metrics. No Node-RED re-import is needed.
