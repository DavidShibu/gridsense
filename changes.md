# GridSense change log

## Two-laptop MQTT deployment

- Added `--broker-host` and `--broker-port` to `simulator.py` so the sensor laptop can connect to the project laptop.
- Added `--lan` to the Aedes demo broker to listen on all IPv4 interfaces. Normal startup remains local-only.
- Added `-RemoteSensor` to the Windows launchers. This starts the project services without a duplicate local sensor simulator.
- Enabled `start.ps1` to forward both `-RemoteSensor` and `-TouDemo` to `start_station.ps1`.
- Corrected the Node-RED broker label from “Local Mosquitto” to “Project laptop MQTT broker (Aedes)”.
- Documented LAN addressing, firewall configuration, connectivity checks and sensor-laptop installation.

## Architecture verification

Confirmed the existing implementation follows the branching diagram in `refererncesss.png`:

```text
Sensor simulator -> MQTT ev/telemetry -> Node-RED
    -> Live dashboard
    -> SQLite commit -> database read -> ML/evaluation -> decision
        -> MQTT ev/actuator -> sensor-side actuator
            -> MQTT ev/ack -> Node-RED -> SQLite control metrics
```

- Verified that analytics reads committed database records and does not depend on the live dashboard.
- Verified that commands return through MQTT and acknowledgements are stored.
- Added a regression test for the complete storage, decision, MQTT and acknowledgement wiring.
- Replayed history and refreshed the five-model training artifacts and evaluation reports.

## Project cleanup

- Removed obsolete Streamlit/legacy application modules, old simulator and service versions, migration scripts and placeholder package code.
- Removed duplicate historical reports, stale exports, old diagrams, flow backups and duplicate model artifacts.
- Removed generated logs, caches and the obsolete `gridsense.db` database.
- Preserved the active `station.db`, installed Python/Node dependencies and Git history locally.
- Backed up removed files and earlier versions of replaced documents in `submission/cleanup-backup.zip`.
- Updated `.gitignore` for local databases, generated files, dependencies and submission output.

## Documentation and dependency updates

- Replaced the README with current installation, single-laptop and two-laptop setup instructions, training steps and verification commands.
- Consolidated current methods, measured results and limitations into `GridSense_Final_Report.md`.
- Updated and rebuilt `GridSense_Presentation.pptx` for the five-model implementation and distributed MQTT deployment.
- Replaced legacy dependency metadata in `pyproject.toml` with the current application's dependencies.
- Added `requirements-tested.txt` recording the Python package versions used for the included trained models.
- Retained `requirements-station.txt` with dependency ranges and documented retraining when model-library versions differ.

## Submission packaging

- Reworked `package_submission.py` to package the current application from an explicit file list and selected source/artifact directories.
- Added previously omitted required files, including `tariff.py`, `tou_scheduler.py`, dashboard templates and validation scripts.
- Included source, tests, setup instructions, final report, presentation, architecture reference, trained models and measured JSON results.
- Added `SUBMISSION_MANIFEST.json` with SHA-256 checksums and ZIP integrity verification.
- Excluded local databases, logs, caches, installed dependencies, Git history and the cleanup backup.
- Created `submission/GridSense_Team3.zip` as the upload artifact. This file has not been uploaded automatically.

## Validation results

- All 29 tests passed from an extracted submission copy.
- Node-RED dashboard templates compiled and flow validation passed.
- Included models loaded successfully from the extracted package and produced a trained decision using a fresh SQLite database.
- The local MQTT integration test stored 1,008 historical observations, five live cycles and five actuator acknowledgements; five commands were accepted.
- The integration test returned dashboard HTTP 200 and observed a maximum site load of 9.5 kW.
- Offline control and tariff comparisons were rerun and their JSON reports refreshed.
- ZIP integrity, checksums, Python syntax and local module dependency checks passed.

## Scope and limitations

The automated integration test ran locally; it did not verify communication between the two physical laptops. Sensor readings and actuator behavior remain simulated. The broker is Aedes and is intended for a trusted LAN; authentication and TLS were not added. Cross-laptop response-time measurements require synchronized clocks. The submission preserves these limitations in its documentation.
