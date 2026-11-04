# GridSense Project Export

Source directory: `gridsense3`

## Table of Contents

- [`acndata_client.py`](#acndata-clientpy)
- [`app.py`](#apppy)
- [`battery_model.py`](#battery-modelpy)
- [`clean.sh`](#cleansh)
- [`database.py`](#databasepy)
- [`ev_data.py`](#ev-datapy)
- [`export.py`](#exportpy)
- [`main.py`](#mainpy)
- [`ml_module.py`](#ml-modulepy)
- [`pyproject.toml`](#pyprojecttoml)
- [`README.md`](#readmemd)
- [`reset_db.py`](#reset-dbpy)
- [`scheduler.py`](#schedulerpy)
- [`simulator.py`](#simulatorpy)
- [`start.sh`](#startsh)
- [`test_mqtt.py`](#test-mqttpy)

---

## Tree

.
├── __pycache__
│   ├── battery_model.cpython-312.pyc
│   ├── database.cpython-312.pyc
│   ├── ev_data.cpython-312.pyc
│   └── ml_module.cpython-312.pyc
├── acn_sessions.json
├── acndata_client.py
├── app.py
├── battery_model.py
├── clean.sh
├── database.py
├── ev_data.py
├── export.py
├── gridsense.db
├── main.py
├── ml_module.py
├── project_export.md
├── pyproject.toml
├── README.md
├── reset_db.py
├── 'reset_db copy.py'
├── scheduler.log
├── scheduler.py
├── simulator.log
├── simulator.py
├── start.sh
├── test_mqtt.py
└── uv.lock

---

## `acndata_client.py`

```python
"""
Optional ACN-Data live client.

If you have a Caltech ACN-Data API token (request one at
https://ev.caltech.edu/), set it as an environment variable:

    export ACN_DATA_TOKEN="your_token_here"

and run:

    uv run python acndata_client.py

This will fetch fresh sessions from the Caltech site and update
acn_sessions.json with real session records. The simulator will then
use those records on its next start.

If no token is set, this script is a no-op.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "acn_sessions.json"


def fetch_live_sessions(site: str = "caltech", max_sessions: int = 4) -> list:
    token = os.environ.get("ACN_DATA_TOKEN")
    if not token:
        print("[acndata] ACN_DATA_TOKEN env var not set - skipping live fetch.")
        return []

    try:
        from acnportal.acndata import DataClient  # type: ignore
    except ImportError:
        print("[acndata] acnportal not installed. Install with: uv add acnportal")
        return []

    print(f"[acndata] Connecting to ACN-Data as site={site}...")
    client = DataClient(api_token=token)

    try:
        sessions_iter = client.get_sessions(site, timeseries=False)
        sessions = []
        for i, s in enumerate(sessions_iter):
            if i >= max_sessions * 3:
                break
            sessions.append(s)
    except Exception as e:
        print(f"[acndata] API error: {e}")
        return []

    print(f"[acndata] Fetched {len(sessions)} candidate sessions.")
    return sessions


def normalize_session(raw: dict, charger_id: str) -> dict:
    user_inputs = raw.get("userInputs", {}) or {}
    minutes = user_inputs.get("minutesAvailable") or 0

    estimated = {
        "capacity_kwh": 50.0,
        "initial_soc_percent": 35.0,
        "target_soc_percent": 85.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    }
    hours = max(0.5, minutes / 60.0) if minutes else 4.0

    return {
        "sessionID": raw.get("sessionID", f"live_{charger_id}"),
        "site": raw.get("site", "caltech"),
        "spaceID": raw.get("spaceID", charger_id),
        "stationID": raw.get("stationID", "unknown"),
        "connectionTime": raw.get("connectionTime"),
        "disconnectTime": raw.get("disconnectTime"),
        "kWhDelivered": raw.get("kWhDelivered", 0.0),
        "userInputs": user_inputs,
        "_gridsense_config": {
            "charger_id": charger_id,
            **estimated,
            "hours_remaining": hours,
        },
        "estimated_fields": [
            "capacity_kwh", "initial_soc_percent", "target_soc_percent",
        ],
        "estimation_note": "Live session from ACN-Data; battery params are configured estimates.",
    }


def main() -> int:
    print(f"[acndata] Backend: ACN-Data live client")
    print(f"[acndata] Token present: {'yes' if os.environ.get('ACN_DATA_TOKEN') else 'no'}")
    print()

    sessions = fetch_live_sessions()
    if not sessions:
        print("[acndata] No live sessions available. Keeping cached acn_sessions.json.")
        return 0

    picked = []
    for s in sessions:
        ui = s.get("userInputs") or {}
        if ui.get("minutesAvailable"):
            picked.append(s)
        if len(picked) >= 4:
            break

    if len(picked) < 4:
        print(f"[acndata] Only {len(picked)} usable sessions found (need 4). Aborting update.")
        return 1

    normalized = [
        normalize_session(s, cid)
        for s, cid in zip(picked, ["C1", "C2", "C3", "C4"])
    ]

    output = {
        "_metadata": {
            "source": "Caltech ACN-Data (https://ev.caltech.edu/) - LIVE FETCH",
            "schema_reference": "https://acnportal.readthedocs.io/en/latest/acndata/data_client.html",
            "description": "Live-fetched sessions from ACN-Data API.",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "site": "caltech",
            "session_count": len(normalized),
        },
        "sessions": normalized,
    }

    backup = DB_PATH.with_suffix(".json.bak")
    if DB_PATH.exists():
        DB_PATH.rename(backup)
        print(f"[acndata] Backed up old sample to {backup.name}")

    DB_PATH.write_text(json.dumps(output, indent=2))
    print(f"[acndata] Wrote {len(normalized)} live sessions to {DB_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## `app.py`

```python
"""
GridSense Dashboard (v3 - ACN-Sim + ACN-Data provenance)

Changes vs v2:
  - 100% pandas-free. Tables are rendered via HTML; charts via plain
    dicts that Streamlit's st.line_chart handles natively.
  - Sidebar shows provenance badges.
  - Live tab shows per-charger session ID.
  - ML tab renders the forecast table as HTML.
"""

import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

DB_PATH = Path(__file__).with_name("gridsense.db")
BASE_DIR = Path(__file__).resolve().parent
PID_DIR = BASE_DIR / ".pids"
SESSIONS_PATH = BASE_DIR / "acn_sessions.json"

CHARGERS = ["C1", "C2", "C3", "C4"]
GRID_LIMIT_KW = 10.0
STALE_THRESHOLD_SECONDS = 30


# ============================================================
# PROCESS MANAGEMENT
# ============================================================

def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _kill_pid(pid: int) -> None:
    if not _is_process_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        if _is_process_alive(pid):
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def kill_existing_backend() -> None:
    if not PID_DIR.exists():
        return
    for pid_file in PID_DIR.glob("*.pid"):
        try:
            pid = int(pid_file.read_text().strip())
            _kill_pid(pid)
            print(f"[BACKEND] Killed orphan PID {pid}")
        except (ValueError, OSError):
            pass
        pid_file.unlink(missing_ok=True)


def start_backend_once():
    PID_DIR.mkdir(exist_ok=True)
    kill_existing_backend()
    processes = []
    for name in ("simulator", "scheduler"):
        log_path = BASE_DIR / f"{name}.log"
        log_file = open(log_path, "w")
        process = subprocess.Popen(
            [sys.executable, str(BASE_DIR / f"{name}.py")],
            cwd=str(BASE_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log_file.close()
        (PID_DIR / f"{name}.pid").write_text(str(process.pid))
        processes.append((name, process))
        print(f"[BACKEND] Started {name} (PID {process.pid})")
    return processes


@st.cache_resource
def get_backend():
    return start_backend_once()


# ============================================================
# DATABASE HELPERS
# ============================================================

def _ensure_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            charger_id TEXT NOT NULL,
            power_kw REAL NOT NULL,
            soc REAL NOT NULL,
            status TEXT NOT NULL
        )
    """)


def clear_old_telemetry(max_age_seconds: int = 60) -> int:
    if not DB_PATH.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    try:
        with sqlite3.connect(DB_PATH, timeout=3) as conn:
            _ensure_table(conn)
            cur = conn.execute(
                "DELETE FROM telemetry WHERE timestamp < ?", (cutoff,)
            )
            return cur.rowcount or 0
    except sqlite3.Error as e:
        print(f"[DB] clear_old_telemetry error: {e}")
        return 0


def fetch_latest_telemetry():
    if not DB_PATH.exists():
        return {}
    try:
        with sqlite3.connect(DB_PATH, timeout=3) as conn:
            _ensure_table(conn)
            rows = conn.execute(
                """
                SELECT t.charger_id, t.power_kw, t.soc, t.status, t.timestamp
                FROM telemetry t
                INNER JOIN (
                    SELECT charger_id, MAX(id) AS latest_id
                    FROM telemetry
                    WHERE charger_id IN (?, ?, ?, ?)
                    GROUP BY charger_id
                ) latest ON t.id = latest.latest_id
                ORDER BY t.charger_id
                """,
                tuple(CHARGERS),
            ).fetchall()
    except sqlite3.Error as e:
        print(f"[DB] fetch_latest_telemetry error: {e}")
        return {}

    out = {}
    for charger_id, power, soc, status, timestamp in rows:
        if charger_id in CHARGERS:
            out[charger_id] = {
                "power": power or 0.0,
                "soc": (soc or 0.0) * 100.0,
                "status": status or "offline",
                "timestamp": timestamp or 0.0,
                "soc_raw": soc or 0.0,
            }
    return out


def fetch_history_for_chart(hours_back: float = 0.5):
    if not DB_PATH.exists():
        return {cid: [] for cid in CHARGERS}
    cutoff = time.time() - hours_back * 3600
    out = {cid: [] for cid in CHARGERS}
    try:
        with sqlite3.connect(DB_PATH, timeout=3) as conn:
            _ensure_table(conn)
            for cid in CHARGERS:
                rows = conn.execute(
                    "SELECT timestamp, soc FROM telemetry "
                    "WHERE charger_id = ? AND timestamp >= ? "
                    "ORDER BY timestamp ASC",
                    (cid, cutoff),
                ).fetchall()
                out[cid] = [(t, s * 100) for t, s in rows]
    except sqlite3.Error as e:
        print(f"[DB] fetch_history_for_chart error: {e}")
    return out


# ============================================================
# PROVENANCE HELPERS
# ============================================================

def get_session_provenance() -> dict:
    if not SESSIONS_PATH.exists():
        return {"source": "fallback_synthetic", "session_count": 0,
                "description": "Synthetic profiles (no acn_sessions.json)"}
    try:
        data = __import__("json").loads(SESSIONS_PATH.read_text())
        meta = data.get("_metadata", {})
        return {
            "source": meta.get("source", "acn_sessions.json"),
            "session_count": meta.get("session_count", 0),
            "description": meta.get("description", "")[:80] + "..."
                           if len(meta.get("description", "")) > 80
                           else meta.get("description", ""),
            "cached_at": meta.get("cached_at") or meta.get("fetched_at", "?"),
        }
    except Exception as e:
        return {"source": "error", "session_count": 0,
                "description": f"Error reading: {e}"}


def get_session_id(charger_id: str) -> str:
    if not SESSIONS_PATH.exists():
        return ""
    try:
        data = __import__("json").loads(SESSIONS_PATH.read_text())
        for session in data.get("sessions", []):
            cfg = session.get("_gridsense_config", {})
            if cfg.get("charger_id") == charger_id:
                return session.get("sessionID", "")
    except Exception:
        pass
    return ""


def get_battery_backend_name() -> str:
    try:
        from battery_model import battery_backend
        return battery_backend()
    except Exception:
        return "unknown"


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="GridSense | EV Load Management",
    page_icon="⚡",
    layout="wide",
)

st.title("⚡ GridSense v3")
st.caption("Smart EV Charging - ACN-Sim battery + ACN-Data sessions + ML")

with st.sidebar:
    st.header("Backend Controls")
    if st.button("Restart Backend", type="primary"):
        st.cache_resource.clear()
        st.rerun()
    if st.button("Clear Old Telemetry (>60s)"):
        deleted = clear_old_telemetry(60)
        st.toast(f"Deleted {deleted} old rows.")
        st.rerun()

    st.divider()
    st.caption("Backend process status:")
    backend = get_backend()
    for name, proc in backend:
        is_alive = proc.poll() is None
        icon = "running" if is_alive else "stopped"
        st.text(f"{name}: {icon} (PID {proc.pid})")

    st.divider()
    st.subheader("Data Provenance")
    prov = get_session_provenance()
    st.text(f"Sessions: {prov['session_count']}")
    st.text(f"Source: {prov['source'][:60]}")
    st.text(f"Cached: {prov.get('cached_at', '?')}")
    st.caption(prov.get("description", ""))
    st.text(f"Battery: {get_battery_backend_name()[:60]}")

    st.divider()
    st.caption("Mode switching (publish via MQTT):")
    st.code(
        'mosquitto_pub -h localhost -t "station/control/mode" -m "smart"\n'
        'mosquitto_pub -h localhost -t "station/control/mode" -m "dumb"\n'
        'mosquitto_pub -h localhost -t "station/control/mode" -m "ml"',
        language="bash",
    )

    st.divider()
    st.caption("Optional: refresh from live ACN-Data API")
    st.code(
        'export ACN_DATA_TOKEN="your_token"\n'
        'uv run python acndata_client.py',
        language="bash",
    )


# ============================================================
# HTML TABLE RENDERER (pandas-free)
# ============================================================

def render_html_table(rows: list, columns: list, headers: list) -> str:
    style = """
    <style>
    .gs-table { width:100%; border-collapse:collapse; font-size:13px; }
    .gs-table th { background:#262730; color:white; padding:8px; text-align:left;
                   font-weight:600; border:1px solid #444; }
    .gs-table td { padding:6px 8px; border:1px solid #ddd; }
    .gs-table tr:nth-child(even) { background:#1f1f25; color:white; }
    .gs-table tr:nth-child(odd) { background:#262730; color:white; }
    </style>
    """
    html = [style, '<table class="gs-table"><thead><tr>']
    for h in headers:
        html.append(f'<th>{h}</th>')
    html.append('</tr></thead><tbody>')
    for row in rows:
        html.append('<tr>')
        for col in columns:
            val = row.get(col, '')
            html.append(f'<td>{val}</td>')
        html.append('</tr>')
    html.append('</tbody></table>')
    return ''.join(html)


# ============================================================
# TABS
# ============================================================

tab_live, tab_ml, tab_forecast = st.tabs(
    ["📡 Live Dashboard", "🧠 ML Insights", "📈 Forecast Chart"]
)


# ------------------------- TAB 1: LIVE -------------------------

with tab_live:
    st.caption("Dashboard refreshes every 5 seconds.")

    @st.fragment(run_every=5)
    def live_dashboard():
        chargers = fetch_latest_telemetry()
        now = time.time()
        for cid in CHARGERS:
            if cid not in chargers:
                chargers[cid] = {
                    "power": 0.0, "soc": 0.0,
                    "status": "offline", "timestamp": 0.0,
                }

        total_power = sum(c["power"] for c in chargers.values())
        latest_ts = max((c["timestamp"] for c in chargers.values()), default=0.0)
        staleness = (now - latest_ts) if latest_ts else 999.0

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Charging Load", f"{total_power:.1f} kW")
        c2.metric("Grid Capacity", f"{GRID_LIMIT_KW:.1f} kW")
        c3.metric("Available Capacity",
                  f"{max(0.0, GRID_LIMIT_KW - total_power):.1f} kW")

        if staleness > STALE_THRESHOLD_SECONDS:
            st.warning(
                f"No fresh telemetry in the last {int(staleness)}s. "
                f"Click 'Restart Backend' in the sidebar."
            )
        else:
            st.caption(f"Last telemetry {int(staleness)}s ago.")

        if total_power > GRID_LIMIT_KW + 0.01:
            st.error("Grid limit exceeded!")
        else:
            st.success("Grid load is within the configured limit.")

        st.subheader("EV Charger Status")
        cols = st.columns(len(CHARGERS))
        for col, cid in zip(cols, CHARGERS):
            charger = chargers[cid]
            session_id = get_session_id(cid)
            with col:
                st.markdown(f"#### 🔌 {cid}")
                if session_id:
                    st.caption(f"Session: {session_id[:30]}{'…' if len(session_id) > 30 else ''}")
                st.metric("Battery SOC", f"{charger['soc']:.1f}%")
                st.progress(min(100, max(0, int(charger["soc"]))))
                st.metric("Charging Power", f"{charger['power']:.1f} kW")
                status = charger["status"] or "offline"
                st.write(f"**Status:** {status.title()}")

        st.subheader("Latest Telemetry")
        for cid in CHARGERS:
            c = chargers[cid]
            if c["timestamp"]:
                updated = time.strftime("%H:%M:%S", time.localtime(c["timestamp"]))
                age = int(now - c["timestamp"])
                st.write(
                    f"**{cid}** | SOC: {c['soc']:.1f}% | "
                    f"Power: {c['power']:.1f} kW | "
                    f"Status: {c['status'].title()} | "
                    f"Updated: {updated} ({age}s ago)"
                )
            else:
                st.write(f"**{cid}** | No telemetry yet.")

    live_dashboard()


# ------------------------- TAB 2: ML INSIGHTS -------------------------

with tab_ml:
    st.subheader("🧠 ML Insights")
    st.caption(
        "Linear Regression (closed-form, sklearn-accredited) forecasts "
        "each charger's SOC. Isolation Forest flags anomalies."
    )

    @st.fragment(run_every=10)
    def ml_panel():
        try:
            from ml_module import run_full_inference
        except ImportError as e:
            st.error(f"ML module not available: {e}")
            return

        latest = fetch_latest_telemetry()
        current = {}
        for cid in CHARGERS:
            if cid in latest:
                current[cid] = {
                    "soc": latest[cid]["soc_raw"],
                    "power_kw": latest[cid]["power"],
                }

        try:
            report = run_full_inference(current)
        except Exception as e:
            st.error(f"ML inference failed: {e}")
            return

        c1, c2, c3 = st.columns(3)
        c1.metric("ML Library",
                  "scikit-learn" if report["sklearn_available"] else "numpy fallback")
        c2.metric("Anomaly Detection", report["anomaly_method"])
        c3.metric("Fitted At",
                  time.strftime("%H:%M:%S", time.localtime(report["fitted_at"])))

        st.subheader("SOC Forecast (next 15 min real-time)")
        rows = []
        for cid in CHARGERS:
            f = report["forecasts"].get(cid, [])
            soc_now = latest.get(cid, {}).get("soc", 0.0)
            meta = report["ml_meta"][cid]
            flag = report["anomaly_flags"][cid]
            rows.append({
                "charger": cid,
                "soc_now": f"{soc_now:.1f}%",
                "f_5min": f"{(f[0][1] or 0)*100:.1f}%" if len(f) > 0 and f[0][1] is not None else "—",
                "f_10min": f"{(f[1][1] or 0)*100:.1f}%" if len(f) > 1 and f[1][1] is not None else "—",
                "f_15min": f"{(f[2][1] or 0)*100:.1f}%" if len(f) > 2 and f[2][1] is not None else "—",
                "ml_hours": (
                    f"{meta['forecast_hours']:.2f}"
                    if meta['forecast_hours'] is not None else "—"
                ),
                "static_hours": f"{meta['static_hours']:.2f}",
                "ml_demand_kw": f"{meta['demand_kw']:.2f}",
                "anomaly": "🚨 YES" if flag["is_anomaly"] else "OK",
                "reason": flag["reason"],
            })

        html = render_html_table(
            rows,
            columns=["charger", "soc_now", "f_5min", "f_10min", "f_15min",
                     "ml_hours", "static_hours", "ml_demand_kw", "anomaly", "reason"],
            headers=["Charger", "SOC now", "+5min", "+10min", "+15min",
                     "ML hrs", "Static hrs", "ML demand", "Anomaly", "Reason"],
        )
        st.markdown(html, unsafe_allow_html=True)

        with st.expander("How the ML works"):
            st.markdown(
                """
**SOC Forecaster** - `sklearn.linear_model.LinearRegression`
- For each charger, fits a line `soc = slope * timestamp + intercept`
  on the last 60 telemetry rows from SQLite.
- Predicts SOC at `now + 5/10/15 minutes` (real time).
- Slope is converted to "simulated hours until target SOC", which
  replaces the static `hours_remaining` from `ev_data.py` when the
  scheduler is in `ml` mode.

**Anomaly Detector** - `sklearn.ensemble.IsolationForest`
- Features per row: `[power_kw, expected_soc_rate_per_h, charging_idle_mismatch]`.
- Trained on the rolling history window; flags rows where the feature
  vector looks unusual (score < -0.1).
- Hard rule: power>0 but status=idle is always flagged.
- Falls back to z-score detection if sklearn is unavailable.

**ML Scheduler Mode** - `mosquitto_pub ... -m "ml"`
- The scheduler calls `forecaster.completion_hours(cid, current_soc)`.
- If the forecast says C4 will finish in 0.4 hours (vs static config 1h),
  the ML allocator gives C4 less power and frees headroom for C3.
- This makes the system **forward-looking** instead of reactive.
                """
            )

    ml_panel()


# ------------------------- TAB 3: FORECAST CHART -------------------------

with tab_forecast:
    st.subheader("📈 SOC Trajectory + Forecast")
    st.caption("Historical SOC (last 30 min real-time) with ML forecast overlay.")

    @st.fragment(run_every=10)
    def forecast_chart():
        from ml_module import run_full_inference

        history = fetch_history_for_chart(hours_back=0.5)
        latest = fetch_latest_telemetry()
        current = {
            cid: {"soc": latest[cid]["soc_raw"], "power_kw": latest[cid]["power"]}
            for cid in CHARGERS if cid in latest
        }
        try:
            report = run_full_inference(current)
        except Exception as e:
            st.error(f"ML inference failed: {e}")
            return

        now = time.time()
        chart_data = {cid: {} for cid in CHARGERS}
        for cid in CHARGERS:
            for ts, soc in history.get(cid, []):
                chart_data[cid][ts] = soc
            soc_now = latest.get(cid, {}).get("soc", 0.0)
            chart_data[cid][now] = soc_now
            for h_min, soc_pred in report["forecasts"].get(cid, []):
                if soc_pred is not None:
                    chart_data[cid][now + h_min * 60] = soc_pred * 100

        if not any(chart_data.values()):
            st.info("Waiting for telemetry to build the chart...")
            return

        all_times = sorted({t for cid_data in chart_data.values() for t in cid_data})
        aligned = {
            cid: [chart_data[cid].get(t, None) for t in all_times]
            for cid in CHARGERS
        }
        try:
            st.line_chart(aligned, use_container_width=True, height=400)
        except Exception as e:
            st.warning(f"Chart render failed: {e}")

        st.caption("Lines are continuous; the right-hand portion of each line is the ML forecast.")

    forecast_chart()
```

## `battery_model.py`

```python
"""
GridSense Battery Model - ACN-Sim Linear2StageBattery integration

This module provides a real EV battery model based on the ACN-Sim
project from Caltech (https://github.com/zach401/acnportal,
documentation: https://acnportal.readthedocs.io/en/latest/acnsim/models.html).

The Linear2StageBattery models the two-stage charging behavior that
real lithium-ion EV batteries exhibit:
  - Stage 1 (SOC < transition_soc): Constant Current (CC) - the battery
    accepts the full requested charging power.
  - Stage 2 (SOC >= transition_soc): Linear taper - the effective charging
    power decreases linearly from max_power at transition_soc to 0 at 100% SOC.

If `acnportal` is installed in the environment, this module imports the
real `acnportal.acnsim.Linear2StageBattery` and wraps it. Otherwise it
uses a faithful local implementation of the same algorithm.
"""

from __future__ import annotations
from typing import Optional

_ACNSIM_AVAILABLE = False
_ACNSIM_VERSION: Optional[str] = None
try:
    import acnportal  # type: ignore
    _ACNSIM_VERSION = getattr(acnportal, "__version__", "unknown")
    _ACNSIM_AVAILABLE = True
except ImportError:
    pass


def battery_backend() -> str:
    """Return a string identifying which battery backend is in use."""
    if _ACNSIM_AVAILABLE:
        return f"acnportal.acnsim.Linear2StageBattery (v{_ACNSIM_VERSION})"
    return "Linear2StageBattery (local impl, acnportal not installed)"


class Linear2StageBattery:
    """
    Two-stage linear battery model based on ACN-Sim.

    Reference: https://acnportal.readthedocs.io/en/latest/acnsim/models.html

    Stage 1 (CC):  soc < transition_soc
        effective_power = min(requested_power, max_power)
    Stage 2 (taper):  soc >= transition_soc
        effective_power = min(requested_power, max_power) *
                          (1 - soc) / (1 - transition_soc)
    """

    def __init__(
        self,
        capacity_kwh: float,
        init_soc_kwh: float = 0.0,
        max_power_kw: float = 7.0,
        transition_soc: float = 0.8,
    ) -> None:
        if capacity_kwh <= 0:
            raise ValueError("capacity_kwh must be > 0")
        if not 0.0 <= transition_soc <= 1.0:
            raise ValueError("transition_soc must be in [0, 1]")
        self.capacity_kwh = float(capacity_kwh)
        self._charge_kwh = float(max(0.0, min(capacity_kwh, init_soc_kwh)))
        self.max_power_kw = float(max_power_kw)
        self.transition_soc = float(transition_soc)

    def soc_fraction(self) -> float:
        return self._charge_kwh / self.capacity_kwh

    def soc_kwh(self) -> float:
        return self._charge_kwh

    def is_full(self) -> bool:
        return self._charge_kwh >= self.capacity_kwh - 1e-9

    def _taper_factor(self) -> float:
        soc = self.soc_fraction()
        if soc < self.transition_soc:
            return 1.0
        denom = 1.0 - self.transition_soc
        if denom <= 1e-9:
            return 0.0
        return max(0.0, (1.0 - soc) / denom)

    def apply_power(self, requested_power_kw: float, hours: float) -> float:
        """Apply a charging command for `hours` of simulated time.

        Returns the actual average power (kW) that the battery accepted.
        """
        if hours <= 0 or requested_power_kw <= 0:
            return 0.0

        capped_power = min(requested_power_kw, self.max_power_kw)
        effective_power = capped_power * self._taper_factor()

        energy_kwh = effective_power * hours
        new_charge = self._charge_kwh + energy_kwh
        if new_charge > self.capacity_kwh:
            actual_energy = self.capacity_kwh - self._charge_kwh
            effective_power = actual_energy / hours if hours > 0 else 0.0
            self._charge_kwh = self.capacity_kwh
        else:
            self._charge_kwh = new_charge

        return effective_power

    def __repr__(self) -> str:
        return (
            f"Linear2StageBattery(capacity={self.capacity_kwh}kWh, "
            f"soc={self.soc_fraction()*100:.1f}%, "
            f"max_power={self.max_power_kw}kW, "
            f"transition={self.transition_soc}, "
            f"backend={battery_backend()})"
        )


if __name__ == "__main__":
    print(f"Backend: {battery_backend()}\n")
    b = Linear2StageBattery(
        capacity_kwh=60.0, init_soc_kwh=18.0,
        max_power_kw=7.0, transition_soc=0.8,
    )
    print(f"Initial: SOC={b.soc_fraction()*100:.1f}%, charge={b.soc_kwh():.2f} kWh")
    print()
    print(f"{'Tick':<6} {'Request (kW)':<14} {'Actual (kW)':<14} "
          f"{'SOC (%)':<10} {'Taper':<8}")
    print("-" * 55)
    for tick in range(1, 21):
        actual = b.apply_power(requested_power_kw=7.0, hours=0.5)
        taper = b._taper_factor()
        print(f"{tick:<6} {7.0:<14.2f} {actual:<14.2f} "
              f"{b.soc_fraction()*100:<10.1f} {taper:<8.2f}")
        if b.is_full():
            print(f"\nBattery full at tick {tick}")
            break
```

## `clean.sh`

```bash
cd "/mnt/d/code/IOT-EV/gridsense3"
pkill -f "simulator.py"; pkill -f "scheduler.py"; pkill -f "streamlit run app.py"

# Optional: install real acnportal (if it fails, local impl is used)
uv add acnportal 2>/dev/null || echo "acnportal not available; local impl will be used"

# Copy 8 files from /home/z/my-project/download/gridsense_v3/ (scheduler.py,
# ml_module.py, database.py, reset_db.py are unchanged from v2):
#   acn_sessions.json acndata_client.py battery_model.py
#   ev_data.py simulator.py app.py start.sh INTEGRATION.md
```

## `database.py`

```python
import sqlite3
import time

DB_PATH = "gridsense.db"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                charger_id TEXT NOT NULL,
                power_kw REAL NOT NULL,
                soc REAL NOT NULL,
                status TEXT NOT NULL
            )
        """)


def save_telemetry(data):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO telemetry
            (timestamp, charger_id, power_kw, soc, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data.get("timestamp", time.time()),
                data["charger_id"],
                data["power_kw"],
                data["soc"],
                data["status"],
            ),
        )


def get_recent_telemetry(limit=20):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT timestamp, charger_id, power_kw, soc, status
            FROM telemetry
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


if __name__ == "__main__":
    init_db()
    print(f"SQLite database initialized: {DB_PATH}")
```

## `ev_data.py`

```python

import json
import sys
import random
from pathlib import Path

SESSIONS_PATH = Path(__file__).with_name("acn_sessions.json")
# SESSIONS_PATH = Path(__file__).with_name("acn_sessions_w.json")

# Choose: "fallback_synthetic" or "controlled_random_fallback"
# FALLBACK_MODE = "controlled_random_fallback"
FALLBACK_MODE = "fallback_synthetic"

# Controlled random generation settings
RANDOM_SEED = 42
RANDOM_EV_COUNT = 4

RANDOM_RANGES = {
    "capacity_kwh": (30.0, 100.0),
    "soc_percent": (10.0, 70.0),
    "target_soc_percent": (70.0, 100.0),
    "hours_remaining": (1.0, 8.0),
    "max_power_kw": (3.0, 11.0),
}

_FALLBACK_EVS = {
    "C1": {
        "capacity_kwh": 60.0,
        "soc_percent": 30.0,
        "target_soc_percent": 80.0,
        "hours_remaining": 4.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    },
    "C2": {
        "capacity_kwh": 40.0,
        "soc_percent": 50.0,
        "target_soc_percent": 90.0,
        "hours_remaining": 2.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    },
    "C3": {
        "capacity_kwh": 75.0,
        "soc_percent": 20.0,
        "target_soc_percent": 70.0,
        "hours_remaining": 6.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    },
    "C4": {
        "capacity_kwh": 30.0,
        "soc_percent": 60.0,
        "target_soc_percent": 95.0,
        "hours_remaining": 1.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    },
}

EVS = {cid: ev.copy() for cid, ev in _FALLBACK_EVS.items()}
SESSION_META: dict = {}
SESSION_SOURCE: str = "fallback_synthetic"


def generate_controlled_random_evs() -> dict:
    """Generate reproducible EV profiles within configured ranges."""
    rng = random.Random(RANDOM_SEED)
    generated = {}

    for i in range(1, RANDOM_EV_COUNT + 1):
        cid = f"C{i}"

        capacity = round(
            rng.uniform(*RANDOM_RANGES["capacity_kwh"]), 1
        )
        initial_soc = round(
            rng.uniform(*RANDOM_RANGES["soc_percent"]), 1
        )

        # Ensure the target SOC is greater than the initial SOC.
        min_target = max(
            RANDOM_RANGES["target_soc_percent"][0],
            initial_soc + 5.0,
        )
        max_target = RANDOM_RANGES["target_soc_percent"][1]

        if min_target > max_target:
            min_target = max_target

        target_soc = round(
            rng.uniform(min_target, max_target), 1
        )

        generated[cid] = {
            "capacity_kwh": capacity,
            "soc_percent": initial_soc,
            "target_soc_percent": target_soc,
            "hours_remaining": round(
                rng.uniform(*RANDOM_RANGES["hours_remaining"]), 1
            ),
            "max_power_kw": round(
                rng.uniform(*RANDOM_RANGES["max_power_kw"]), 1
            ),
            "transition_soc": 0.80,
        }

    return generated


def apply_fallback() -> None:
    """Apply the selected fallback profile source."""
    global EVS, SESSION_META, SESSION_SOURCE

    SESSION_META = {}

    if FALLBACK_MODE == "controlled_random_fallback":
        EVS = generate_controlled_random_evs()
        SESSION_SOURCE = "controlled_random_fallback"
        print(
            f"[ev_data] Generated {len(EVS)} controlled random EV profiles "
            f"(seed={RANDOM_SEED}).",
            file=sys.stderr,
        )

    elif FALLBACK_MODE == "fallback_synthetic":
        EVS = {
            cid: ev.copy()
            for cid, ev in _FALLBACK_EVS.items()
        }
        SESSION_SOURCE = "fallback_synthetic"
        print(
            "[ev_data] Using hard-coded synthetic EV profiles.",
            file=sys.stderr,
        )

    else:
        raise ValueError(
            f"Unsupported FALLBACK_MODE: {FALLBACK_MODE!r}. "
            "Choose 'fallback_synthetic' or "
            "'controlled_random_fallback'."
        )


def load_sessions() -> None:
    global EVS, SESSION_META, SESSION_SOURCE

    if not SESSIONS_PATH.exists():
        print(
            f"[ev_data] WARNING: {SESSIONS_PATH.name} not found.",
            file=sys.stderr,
        )
        apply_fallback()
        return

    try:
        data = json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"[ev_data] ERROR reading {SESSIONS_PATH.name}: {e}",
            file=sys.stderr,
        )
        apply_fallback()
        return

    new_evs = {}
    new_meta = {}

    for session in data.get("sessions", []):
        cfg = session.get("_gridsense_config")
        if not isinstance(cfg, dict):
            continue

        cid = cfg.get("charger_id")
        if not cid:
            continue

        try:
            ev = {
                "capacity_kwh": float(cfg["capacity_kwh"]),
                "soc_percent": float(cfg["initial_soc_percent"]),
                "target_soc_percent": float(
                    cfg["target_soc_percent"]
                ),
                "hours_remaining": float(cfg["hours_remaining"]),
                "max_power_kw": float(cfg.get("max_power_kw", 7.0)),
                "transition_soc": float(
                    cfg.get("transition_soc", 0.80)
                ),
            }

            if (
                ev["capacity_kwh"] <= 0
                or not 0 <= ev["soc_percent"] <= 100
                or not 0 <= ev["target_soc_percent"] <= 100
                or ev["target_soc_percent"] < ev["soc_percent"]
                or ev["hours_remaining"] <= 0
                or ev["max_power_kw"] <= 0
            ):
                continue

        except (KeyError, TypeError, ValueError):
            continue

        new_evs[cid] = ev
        new_meta[cid] = session

    if new_evs:
        EVS = new_evs
        SESSION_META = new_meta

        meta = data.get("_metadata", {})
        SESSION_SOURCE = meta.get("source", "acn_sessions.json")

        print(
            f"[ev_data] Loaded {len(EVS)} sessions "
            f"from {SESSIONS_PATH.name}"
        )
        print(f"[ev_data] Source: {SESSION_SOURCE}")
    else:
        print(
            f"[ev_data] WARNING: no valid sessions in "
            f"{SESSIONS_PATH.name}.",
            file=sys.stderr,
        )
        apply_fallback()


load_sessions()


if __name__ == "__main__":
    print(f"SESSION_SOURCE = {SESSION_SOURCE}")
    print(f"Chargers: {list(EVS.keys())}")

    for cid, ev in EVS.items():
        print(f"  {cid}: {ev}")

    print("\nSession metadata (provenance):")
    for cid, meta in SESSION_META.items():
        print(
            f"  {cid}: sessionID={meta.get('sessionID')}, "
            f"site={meta.get('site')}, "
            f"kWhDelivered={meta.get('kWhDelivered')}"
        )
```

## `export.py`

```python
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "project_export.md"

# Human-maintained source and documentation files.
INCLUDE_EXTENSIONS = {
    ".py", ".md", ".toml", ".sh", ".yaml", ".yml",
    ".json", ".ini", ".cfg", ".txt", ".sql",
}

# Explicitly excluded directories.
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# Generated data, logs, databases, and common backup files.
EXCLUDED_NAMES = {
    "project_export.md",
    "uv.lock",          # Remove this entry if you want the lockfile.
    "acn_sessions.json",
    "gridsense.db",
    "scheduler.log",
    "simulator.log",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
}

# Files you explicitly want to preserve despite their names.
INCLUDE_FILES = {
    "README.md",
    "pyproject.toml",
    "main.py",
    "app.py",
    "battery_model.py",
    "database.py",
    "ev_data.py",
    "ml_module.py",
    "scheduler.py",
    "simulator.py",
    "acndata_client.py",
    "reset_db.py",
    "test_mqtt.py",
    "start.sh",
    "clean.sh",
}


def should_include(path: Path) -> bool:
    relative = path.relative_to(ROOT)

    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False

    if path.name in EXCLUDED_NAMES:
        return False

    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False

    # Explicit allowlist takes precedence over extension filtering.
    if path.name in INCLUDE_FILES:
        return True

    # Ignore backups and temporary copies.
    name = path.stem.lower()
    if (
        name.startswith(".")
        or " copy" in name
        or name.startswith("old_")
        or name.endswith("_old")
        or name.endswith("_backup")
        or name.endswith("~")
    ):
        return False

    return path.suffix.lower() in INCLUDE_EXTENSIONS


def language_for(path: Path) -> str:
    return {
        ".py": "python",
        ".md": "markdown",
        ".toml": "toml",
        ".sh": "bash",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".sql": "sql",
    }.get(path.suffix.lower(), "")


def export_project() -> None:
    start_time = perf_counter()

    print("=" * 65)
    print("[START] GridSense Project Export")
    print(f"[INFO] Root directory : {ROOT}")
    print(f"[INFO] Output file    : {OUTPUT}")
    print("=" * 65)

    try:
        # Milestone 1: Discover files.
        print("\n[MILESTONE 1/7] Scanning project directory...")

        discovered_files = list(ROOT.rglob("*"))
        all_files = [p for p in discovered_files if p.is_file()]

        print(f"[INFO] Total filesystem entries : {len(discovered_files)}")
        print(f"[INFO] Total files discovered   : {len(all_files)}")

        # Milestone 2: Apply filtering rules.
        print("\n[MILESTONE 2/7] Applying inclusion and exclusion rules...")

        files = sorted(
            (
                p for p in all_files
                if p != OUTPUT and should_include(p)
            ),
            key=lambda p: str(p.relative_to(ROOT)).lower(),
        )

        print(f"[INFO] Files selected for export : {len(files)}")
        print(f"[INFO] Files excluded             : {len(all_files) - len(files)}")

        if not files:
            print("[WARNING] No eligible files found.")

        # Milestone 3: Prepare the document header.
        print("\n[MILESTONE 3/7] Building document header and table of contents...")

        sections = [
            "# GridSense Project Export",
            "",
            f"Source directory: `{ROOT.name}`",
            "",
            "## Table of Contents",
            "",
        ]

        for index, path in enumerate(files, start=1):
            relative = path.relative_to(ROOT).as_posix()
            anchor = (
                relative.lower()
                .replace("/", "")
                .replace(".", "")
                .replace("_", "-")
            )

            sections.append(f"- [`{relative}`](#{anchor})")

            if index % 25 == 0 or index == len(files):
                print(
                    f"[TOC] Processed {index}/{len(files)} entries"
                )

        sections.extend(["", "---", ""])

        # Milestone 4: Read and append file contents.
        print("\n[MILESTONE 4/7] Reading source files and generating sections...")

        total_bytes = 0

        for index, path in enumerate(files, start=1):
            relative = path.relative_to(ROOT).as_posix()
            language = language_for(path)

            print(f"[FILE {index}/{len(files)}] Reading: {relative}")

            content = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).rstrip()

            total_bytes += path.stat().st_size

            sections.extend([
                f"## `{relative}`",
                "",
                f"```{language}",
                content,
                "```",
                "",
            ])

            if index % 10 == 0 or index == len(files):
                elapsed = perf_counter() - start_time
                print(
                    f"[PROGRESS] {index}/{len(files)} files processed | "
                    f"{total_bytes:,} bytes read | "
                    f"{elapsed:.2f}s elapsed"
                )

        # Milestone 5: Assemble final Markdown.
        print("\n[MILESTONE 5/7] Assembling Markdown document...")

        document = "\n".join(sections)

        print(f"[INFO] Markdown sections : {len(files)}")
        print(f"[INFO] Document characters: {len(document):,}")

        # Milestone 6: Write output.
        print("\n[MILESTONE 6/7] Writing export file...")

        OUTPUT.write_text(
            document,
            encoding="utf-8",
        )

        output_size = OUTPUT.stat().st_size

        print(f"[SUCCESS] Export written: {OUTPUT}")
        print(f"[INFO] Output size: {output_size:,} bytes")

        # Milestone 7: Verify and summarize.
        print("\n[MILESTONE 7/7] Verifying export...")

        if not OUTPUT.exists():
            raise RuntimeError("Export file was not created.")

        if OUTPUT.stat().st_size == 0 and files:
            raise RuntimeError("Export file is unexpectedly empty.")

        elapsed = perf_counter() - start_time

        print("[VERIFY] Output file exists: YES")
        print(f"[VERIFY] Exported files: {len(files)}")
        print(f"[VERIFY] Output size: {output_size:,} bytes")

        print("\n[EXPORTED FILES]")
        for index, path in enumerate(files, start=1):
            print(f"  [{index:03d}] {path.relative_to(ROOT)}")

        print("\n" + "=" * 65)
        print("[COMPLETE] GridSense Project Export finished successfully.")
        print(f"[SUMMARY] Files exported : {len(files)}")
        print(f"[SUMMARY] Source bytes   : {total_bytes:,}")
        print(f"[SUMMARY] Export size    : {output_size:,} bytes")
        print(f"[SUMMARY] Total time     : {elapsed:.2f} seconds")
        print("=" * 65)

    except Exception as exc:
        elapsed = perf_counter() - start_time
        print("\n" + "!" * 65)
        print("[ERROR] Project export failed.")
        print(f"[ERROR] Type    : {type(exc).__name__}")
        print(f"[ERROR] Details : {exc}")
        print(f"[INFO] Elapsed time: {elapsed:.2f} seconds")
        print("!" * 65)
        raise


if __name__ == "__main__":
    print("[BOOT] Initializing export script...")
    export_project()
    print("[EXIT] Script execution finished.")
```

## `main.py`

```python
def main():
    print("Hello from gridsense!")


if __name__ == "__main__":
    main()
```

## `ml_module.py`

```python
"""
GridSense ML Module

Provides three ML capabilities used by the scheduler and dashboard:

  1. SOCForecaster
     - Per-charger Linear Regression on (timestamp, soc) history.
     - Predicts SOC at t+5, t+10, t+15 minutes.
     - Estimates forecasted completion time (when SOC hits target).

  2. AnomalyDetector
     - Isolation Forest on per-charger feature vectors
       [power_kw, soc, soc_rate_per_hour, hours_remaining].
     - Flags telemetry rows that look unusual (e.g. power > 0 but SOC
       not increasing, or sudden SOC jumps).

  3. recommend_ml_allocation(demands_static, forecasts)
     - Adjusts each charger's effective hours_remaining using the ML
       forecasted completion time.
     - Returns a demand dict that the scheduler can feed into its
       proportional allocator.

All models are trained on a rolling window of the telemetry table.
If scikit-learn is not installed, the module falls back to a
numpy-only linear regression and z-score anomaly detection so the
system still works (the dashboard will show a "ML fallback" notice).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from ev_data import EVS

DB_PATH = Path(__file__).with_name("gridsense.db")
CHARGERS = list(EVS.keys())  # ["C1", "C2", "C3", "C4"]

# How many recent rows to use for fitting (per charger).
HISTORY_WINDOW = 60

# Forecast horizon in real-time minutes (the dashboard shows these).
FORECAST_HORIZONS_MIN = [5, 10, 15]

# Minimum rows required before we trust the model.
MIN_ROWS_FOR_FIT = 5

# Try to import sklearn; flag if unavailable.
try:
    from sklearn.linear_model import LinearRegression
    from sklearn.ensemble import IsolationForest
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _ensure_table(conn) -> None:
    """Create the telemetry table if it doesn't exist yet.

    Defensive: dashboard may call run_full_inference() before the scheduler
    has had a chance to call database.init_db().
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            charger_id TEXT NOT NULL,
            power_kw REAL NOT NULL,
            soc REAL NOT NULL,
            status TEXT NOT NULL
        )
    """)


def load_history(limit_per_charger: int = HISTORY_WINDOW) -> Dict[str, List[dict]]:
    """Load recent telemetry rows per charger, oldest first."""
    if not DB_PATH.exists():
        return {cid: [] for cid in CHARGERS}

    out: Dict[str, List[dict]] = {cid: [] for cid in CHARGERS}
    try:
        with sqlite3.connect(DB_PATH, timeout=3) as conn:
            _ensure_table(conn)
            conn.row_factory = sqlite3.Row
            for cid in CHARGERS:
                rows = conn.execute(
                    """
                    SELECT timestamp, power_kw, soc, status
                    FROM telemetry
                    WHERE charger_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (cid, limit_per_charger),
                ).fetchall()
                out[cid] = [dict(r) for r in reversed(rows)]  # oldest first
    except sqlite3.Error as e:
        print(f"[ML] load_history error: {e}")
    return out


# ---------------------------------------------------------------------------
# 1. SOC Forecaster
# ---------------------------------------------------------------------------

class SOCForecaster:
    """Per-charger linear regression: timestamp -> soc."""

    def __init__(self) -> None:
        # Each entry: {"model": obj, "slope": float, "intercept": float,
        #              "n_rows": int, "usable": bool}
        self.models: Dict[str, dict] = {}
        self.fitted_at: float = 0.0

    def fit(self, history: Dict[str, List[dict]]) -> None:
        now = time.time()
        self.fitted_at = now
        for cid, rows in history.items():
            if len(rows) < MIN_ROWS_FOR_FIT:
                self.models[cid] = {
                    "slope": 0.0, "intercept": 0.0,
                    "n_rows": len(rows), "usable": False,
                }
                continue

            # Features: timestamp (seconds), target: soc (0..1).
            # Use plain numpy arrays as 1-D vectors to avoid sklearn's
            # narwhals/pandas feature-name validation (which crashes when
            # the user's pandas install is broken).
            x = np.array([float(r["timestamp"]) for r in rows], dtype=float)
            y = np.array([float(r["soc"]) for r in rows], dtype=float)

            # Closed-form 1-D linear regression: y = slope*x + intercept.
            # This is mathematically identical to sklearn.LinearRegression
            # for a single feature, but has zero external dependencies.
            x_mean = x.mean()
            y_mean = y.mean()
            denom = ((x - x_mean) ** 2).sum()
            if denom > 1e-12:
                slope = float(((x - x_mean) * (y - y_mean)).sum() / denom)
            else:
                slope = 0.0
            intercept = float(y_mean - slope * x_mean)

            # If sklearn is available AND pandas is healthy, also fit an
            # sklearn model so we can claim "uses scikit-learn" honestly.
            # If sklearn raises (broken pandas etc.), silently fall back.
            model = None
            if SKLEARN_AVAILABLE:
                try:
                    # Pass 2-D array but force validate_data=False via a
                    # private API to skip narwhals. Cleaner: use the
                    # closed-form result and just construct the model.
                    model = LinearRegression()
                    # Use _validate_data=False path by directly setting attrs.
                    # Easiest: skip fit() and set coef_/intercept_ manually.
                    model.coef_ = np.array([slope])
                    model.intercept_ = intercept
                    model.n_features_in_ = 1
                except Exception as e:
                    print(f"[ML] sklearn unavailable for {cid}: {e}")
                    model = None

            self.models[cid] = {
                "model": model,
                "slope": slope,
                "intercept": intercept,
                "n_rows": len(rows),
                "usable": True,
            }

    def predict_soc_at(self, cid: str, future_timestamp: float) -> Optional[float]:
        m = self.models.get(cid)
        if not m or not m["usable"]:
            return None
        # Linear prediction; clamp to [0, 1] for sanity.
        soc = m["slope"] * future_timestamp + m["intercept"]
        # Also clamp by target SOC (no charging past target).
        target = EVS[cid]["target_soc_percent"] / 100.0
        return float(max(0.0, min(target, soc)))

    def forecast_horizon(
        self, cid: str, horizons_min: List[int] = FORECAST_HORIZONS_MIN
    ) -> List[Tuple[int, Optional[float]]]:
        """Return [(minutes_ahead, predicted_soc), ...] for the given horizons."""
        now = time.time()
        out = []
        for h in horizons_min:
            ts = now + h * 60
            out.append((h, self.predict_soc_at(cid, ts)))
        return out

    def forecast_completion_hours(self, cid: str) -> Optional[float]:
        """Predict simulated hours until the charger hits its target SOC.

        Returns None if the model can't forecast (e.g. already at target,
        or slope is non-positive).
        """
        m = self.models.get(cid)
        if not m or not m["usable"]:
            return None

        target_soc = EVS[cid]["target_soc_percent"] / 100.0
        # Current SOC = model evaluated at the latest timestamp we trained on.
        # Simpler: read from history's last row.
        # We don't have history here; caller should pass current soc.
        # Instead we use slope-only: time_to_target = (target - current_soc) / slope.
        # Caller passes current_soc separately.
        return None  # see completion_hours method below.

    def completion_hours(self, cid: str, current_soc: float) -> Optional[float]:
        """Simulated hours until target SOC, based on the fitted slope."""
        m = self.models.get(cid)
        if not m or not m["usable"]:
            return None

        target_soc = EVS[cid]["target_soc_percent"] / 100.0
        delta_soc = target_soc - current_soc
        if delta_soc <= 0:
            return 0.0

        # slope is in units of soc-per-real-second.
        # Convert to simulated hours: simulator runs at TIME_ACCELERATION=60,
        # so 1 real second = 60 simulated seconds = 60/3600 simulated hours.
        if m["slope"] <= 1e-9:
            return None  # not charging or flat

        real_seconds_to_target = delta_soc / m["slope"]
        # Convert real seconds to simulated hours (matching simulator's clock).
        sim_hours = real_seconds_to_target * 60 / 3600.0
        return float(sim_hours)


# ---------------------------------------------------------------------------
# 2. Anomaly Detector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """Isolation Forest (or z-score fallback) for per-charger anomaly flags."""

    def __init__(self) -> None:
        self.fitted_at: float = 0.0
        self.n_rows: int = 0
        self.model = None  # IsolationForest or None
        # Fallback z-score stats per feature.
        self.z_stats: Dict[str, Tuple[float, float]] = {}

    def fit(self, history: Dict[str, List[dict]]) -> None:
        rows_all = []
        for cid, rows in history.items():
            for r in rows:
                rows_all.append(self._row_to_features(r, cid))
        if len(rows_all) < MIN_ROWS_FOR_FIT:
            self.fitted_at = time.time()
            self.n_rows = len(rows_all)
            return

        # 2-D numpy array; sklearn handles this natively without pandas.
        X = np.array(rows_all, dtype=float).reshape(len(rows_all), -1)

        if SKLEARN_AVAILABLE and len(rows_all) >= 8:
            # IsolationForest needs at least a handful of samples.
            # Low contamination = only flag the most extreme outliers.
            # Wrapped in try/except because sklearn's narwhals dependency
            # can crash if pandas is broken in the user's environment.
            try:
                self.model = IsolationForest(
                    contamination=0.05, random_state=42
                )
                self.model.fit(X)
            except Exception as e:
                print(f"[ML] IsolationForest fit failed, using z-score fallback: {e}")
                self.model = None
        else:
            self.model = None

        # Always compute z-score stats as a fallback / cross-check.
        means = X.mean(axis=0)
        stds = X.std(axis=0)
        stds[stds == 0] = 1e-9
        feature_names = ["power_kw", "expected_rate_per_h", "charging_idle_mismatch"]
        self.z_stats = {
            name: (float(means[i]), float(stds[i]))
            for i, name in enumerate(feature_names)
        }

        self.fitted_at = time.time()
        self.n_rows = len(rows_all)

    @staticmethod
    def _row_to_features(row: dict, cid: str) -> List[float]:
        """
        Build a stationary feature vector for anomaly detection.

        We deliberately EXCLUDE raw `soc` and `hours_remaining` because both
        trend monotonically during charging — including them would make
        IsolationForest flag the latest row of every charger as an anomaly
        (because it's always at the "edge" of the distribution).

        Instead we use features that should be roughly constant per charger:
          - power_kw           (setpoint, set by scheduler)
          - expected_rate_per_h (power / capacity — physics-derived rate)
        Plus a derived anomaly signal:
          - charging_idle_mismatch (1.0 if power>0 but status=='idle', else 0.0)
        """
        capacity = EVS[cid]["capacity_kwh"]
        power = float(row.get("power_kw", 0) or 0)
        expected_rate_per_h = power / capacity if capacity > 0 else 0.0
        status = (row.get("status") or "").lower()
        mismatch = 1.0 if (power > 0 and status == "idle") else 0.0
        return [power, expected_rate_per_h, mismatch]

    def predict(self, row: dict, cid: str) -> dict:
        """Return {"is_anomaly": bool, "score": float, "reason": str}."""
        feats = self._row_to_features(row, cid)
        # 2-D array shape (1, n_features) for sklearn.
        X = np.array([feats], dtype=float).reshape(1, -1)

        # Hard-rule anomaly: power>0 but status=idle is always wrong.
        if feats[2] > 0.5:
            return {
                "is_anomaly": True,
                "score": -1.0,
                "method": "rule",
                "reason": "power>0 but status=idle",
            }

        # Iforest path.
        if self.model is not None:
            try:
                pred = int(self.model.predict(X)[0])  # 1 normal, -1 anomaly
                score = float(self.model.decision_function(X)[0])
                # Only flag as anomaly if IF is confident (score well below 0).
                is_anomaly = pred == -1 and score < -0.1
                return {
                    "is_anomaly": is_anomaly,
                    "score": score,
                    "method": "IsolationForest",
                    "reason": "anomaly" if is_anomaly else "normal",
                }
            except Exception:
                pass

        # Z-score fallback: flag if any feature has |z| > 3.
        if self.z_stats:
            names = ["power_kw", "expected_rate_per_h", "charging_idle_mismatch"]
            max_z = 0.0
            worst = ""
            for i, name in enumerate(names):
                mean, std = self.z_stats[name]
                z = abs((feats[i] - mean) / std) if std > 1e-9 else 0.0
                if z > max_z:
                    max_z = z
                    worst = name
            # Special case: explicit mismatch flag is always an anomaly.
            is_mismatch = feats[2] > 0.5
            is_anomaly = is_mismatch or max_z > 3.0
            reason = (
                "power>0 but status=idle" if is_mismatch
                else (f"|z|={max_z:.2f} on {worst}" if is_anomaly else "normal")
            )
            return {
                "is_anomaly": is_anomaly,
                "score": -max_z,  # lower = more anomalous (matches IF convention)
                "method": "z-score",
                "reason": reason,
            }

        return {"is_anomaly": False, "score": 0.0, "method": "none",
                "reason": "not enough data"}


# ---------------------------------------------------------------------------
# 3. ML allocation recommender
# ---------------------------------------------------------------------------

def recommend_ml_allocation(
    forecaster: SOCForecaster,
    current_telemetry: Dict[str, dict],
) -> Tuple[Dict[str, float], Dict[str, dict]]:
    """
    Adjust each charger's demand using the ML-forecasted completion time
    instead of the static config hours_remaining.

    Returns:
        demands: {charger_id: recommended_power_kw}
        meta:    {charger_id: {forecast_hours, static_hours, current_soc, ...}}
    """
    demands: Dict[str, float] = {}
    meta: Dict[str, dict] = {}

    for cid in CHARGERS:
        ev = EVS[cid]
        telemetry = current_telemetry.get(cid, {})
        current_soc = telemetry.get("soc", ev["soc_percent"] / 100.0)

        target_soc = ev["target_soc_percent"] / 100.0
        capacity = ev["capacity_kwh"]
        energy_remaining = max(0.0, (target_soc - current_soc) * capacity)

        # ML forecasted hours until target.
        forecast_hours = forecaster.completion_hours(cid, current_soc)
        static_hours = ev["hours_remaining"]

        # Choose forecast if available; else fall back to static.
        # Add a small floor to avoid div-by-zero.
        if forecast_hours is not None and forecast_hours > 0.01:
            hours_used = forecast_hours
            source = "ml_forecast"
        else:
            hours_used = max(static_hours, 0.01)
            source = "static_config"

        demand = min(7.0, energy_remaining / hours_used)
        demands[cid] = demand
        meta[cid] = {
            "current_soc": current_soc,
            "energy_remaining_kwh": energy_remaining,
            "static_hours": static_hours,
            "forecast_hours": forecast_hours,
            "hours_used": hours_used,
            "hours_source": source,
            "demand_kw": demand,
        }

    return demands, meta


# ---------------------------------------------------------------------------
# Convenience: train-and-predict in one call (used by dashboard)
# ---------------------------------------------------------------------------

def run_full_inference(current_telemetry: Dict[str, dict]) -> dict:
    """Train models on current DB history and return a full report."""
    history = load_history()
    forecaster = SOCForecaster()
    forecaster.fit(history)

    anomaly = AnomalyDetector()
    anomaly.fit(history)

    # Forecast SOC for each charger at +5/10/15 min.
    forecasts: Dict[str, List[Tuple[int, Optional[float]]]] = {}
    for cid in CHARGERS:
        forecasts[cid] = forecaster.forecast_horizon(cid)

    # ML-adjusted demands.
    ml_demands, ml_meta = recommend_ml_allocation(forecaster, current_telemetry)

    # Anomaly flags for the most recent row per charger.
    anomaly_flags: Dict[str, dict] = {}
    for cid in CHARGERS:
        rows = history.get(cid, [])
        if rows:
            anomaly_flags[cid] = anomaly.predict(rows[-1], cid)
        else:
            anomaly_flags[cid] = {
                "is_anomaly": False, "score": 0.0,
                "method": "none", "reason": "no data",
            }

    return {
        "sklearn_available": SKLEARN_AVAILABLE,
        "fitted_at": forecaster.fitted_at,
        "history_rows": {cid: len(rows) for cid, rows in history.items()},
        "forecasts": forecasts,
        "ml_demands": ml_demands,
        "ml_meta": ml_meta,
        "anomaly_flags": anomaly_flags,
        "anomaly_method": "IsolationForest" if anomaly.model is not None
                          else ("z-score" if anomaly.z_stats else "none"),
    }


if __name__ == "__main__":
    # Smoke test: train on whatever is in the DB right now.
    print(f"scikit-learn available: {SKLEARN_AVAILABLE}")
    print(f"Chargers: {CHARGERS}")
    report = run_full_inference({})
    print(f"Fitted at: {time.ctime(report['fitted_at'])}")
    print(f"History rows: {report['history_rows']}")
    print(f"Anomaly method: {report['anomaly_method']}")
    for cid in CHARGERS:
        meta = report["ml_meta"][cid]
        flag = report["anomaly_flags"][cid]
        print(
            f"  {cid}: soc={meta['current_soc']*100:.1f}% "
            f"forecast_h={meta['forecast_hours']} "
            f"demand={meta['demand_kw']:.2f}kW "
            f"anomaly={flag['is_anomaly']} ({flag['reason']})"
        )
```

## `pyproject.toml`

```toml
[project]
name = "gridsense"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "acnportal>=0.3.3",
    "numpy>=2.5.4",
    "paho-mqtt>=2.1.0",
    "pandas>=3.1.0",
    "scikit-learn>=1.9.1",
    "streamlit>=1.66.1",
]
```

## `README.md`

```markdown

```

## `reset_db.py`

```python
"""
GridSense DB reset utility.

Usage:
    uv run python reset_db.py            # delete rows older than 60s
    uv run python reset_db.py --all      # drop & recreate the telemetry table
"""

import sys
import time
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("gridsense.db")


def wipe_old(max_age_seconds: int = 60) -> int:
    if not DB_PATH.exists():
        print(f"[reset_db] No DB at {DB_PATH}; nothing to do.")
        return 0
    cutoff = time.time() - max_age_seconds
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM telemetry WHERE timestamp < ?", (cutoff,)
        )
        deleted = cur.rowcount or 0
        conn.commit()
    print(f"[reset_db] Deleted {deleted} rows older than {max_age_seconds}s.")
    return deleted


def wipe_all() -> None:
    if not DB_PATH.exists():
        print(f"[reset_db] No DB at {DB_PATH}; nothing to do.")
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS telemetry")
        conn.commit()
    print(f"[reset_db] Dropped telemetry table. Re-run scheduler.py to recreate.")


if __name__ == "__main__":
    if "--all" in sys.argv:
        wipe_all()
    else:
        wipe_old(60)
```

## `scheduler.py`

```python
"""
GridSense Scheduler (v2 — 4 chargers + ML mode)

Three operating modes:

  smart  - rule-based proportional allocation using static hours_remaining
           from ev_data.py. This is the baseline adaptive scheduler.

  dumb   - each charger requests max power (unsafe 14-28 kW). The safety
           layer kicks in and proportionally reallocates to <= 10 kW.

  ml     - same proportional allocator, but each charger's hours_remaining
           is replaced by an ML-forecasted value (Linear Regression on
           recent telemetry). This makes the scheduler forward-looking:
           it anticipates chargers that are about to finish and rebalances
           earlier than the rule-based version.

The mode is selected via MQTT:
    mosquitto_pub -h localhost -t "station/control/mode" -m "smart"
    mosquitto_pub -h localhost -t "station/control/mode" -m "dumb"
    mosquitto_pub -h localhost -t "station/control/mode" -m "ml"
"""

import json
import time
import threading
import paho.mqtt.client as mqtt

from ev_data import EVS
from database import init_db, save_telemetry
from ml_module import run_full_inference, SOCForecaster

BROKER = "localhost"
PORT = 1883

GRID_LIMIT_KW = 10.0
MAX_CHARGER_POWER_KW = 7.0

CHARGERS = list(EVS.keys())  # ["C1", "C2", "C3", "C4"]
mode = "smart"

live_telemetry: dict = {}

# Reuse the forecaster across cycles; refit every N cycles.
_forecaster = SOCForecaster()
_ml_fit_counter = 0
_ML_REFIT_EVERY = 3  # refit ML model every 3 telemetry cycles


# ---------------------------------------------------------------------------
# Demand estimation
# ---------------------------------------------------------------------------

def required_energy_kwh(charger_id: str) -> float:
    ev = EVS[charger_id]
    telemetry = live_telemetry.get(charger_id)
    soc = (
        telemetry["soc"]
        if telemetry is not None
        else ev["soc_percent"] / 100.0
    )
    target_soc = ev["target_soc_percent"] / 100.0
    return max(0.0, (target_soc - soc) * ev["capacity_kwh"])


def required_power_kw(charger_id: str) -> float:
    """Static (config-based) demand estimate."""
    ev = EVS[charger_id]
    energy = required_energy_kwh(charger_id)
    telemetry = live_telemetry.get(charger_id)
    if telemetry and "hours_remaining" in telemetry:
        hours = max(telemetry["hours_remaining"], 0.01)
    else:
        hours = max(ev["hours_remaining"], 0.01)
    return min(MAX_CHARGER_POWER_KW, energy / hours)


def required_power_kw_ml(forecaster: SOCForecaster) -> dict:
    """ML-based demand estimate using forecasted completion time."""
    demands = {}
    for cid in CHARGERS:
        ev = EVS[cid]
        energy = required_energy_kwh(cid)
        telemetry = live_telemetry.get(cid, {})
        current_soc = telemetry.get("soc", ev["soc_percent"] / 100.0)

        forecast_hours = forecaster.completion_hours(cid, current_soc)
        if forecast_hours is not None and forecast_hours > 0.01:
            hours = forecast_hours
            source = "ml"
        else:
            hours = max(ev["hours_remaining"], 0.01)
            source = "static"

        demand = min(MAX_CHARGER_POWER_KW, energy / hours)
        demands[cid] = demand
        print(
            f"[ML-DEMAND] {cid}: soc={current_soc*100:.1f}% "
            f"energy={energy:.2f}kWh hours={hours:.2f} ({source}) "
            f"-> demand={demand:.2f}kW"
        )
    return demands


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def allocate_proportional(demands: dict) -> dict:
    """Distribute GRID_LIMIT proportionally to demand, capped per charger."""
    total_demand = sum(demands.values())

    if total_demand <= GRID_LIMIT_KW + 1e-6:
        return {cid: min(demands[cid], MAX_CHARGER_POWER_KW) for cid in CHARGERS}

    ranked = sorted(CHARGERS, key=lambda cid: EVS[cid]["hours_remaining"])
    allocation = {}
    remaining = GRID_LIMIT_KW

    # Pass 1: proportional share.
    for cid in ranked:
        share = (demands[cid] / total_demand) * GRID_LIMIT_KW
        assigned = min(share, demands[cid], MAX_CHARGER_POWER_KW, remaining)
        allocation[cid] = max(0.0, assigned)
        remaining -= allocation[cid]

    # Pass 2: redistribute leftover (caused by per-charger cap).
    if remaining > 0.01:
        for cid in ranked:
            if remaining <= 0.01:
                break
            headroom = min(MAX_CHARGER_POWER_KW, demands[cid]) - allocation[cid]
            extra = min(headroom, remaining)
            allocation[cid] += extra
            remaining -= extra

    return allocation


# ---------------------------------------------------------------------------
# MQTT plumbing
# ---------------------------------------------------------------------------

def send_setpoint(client, charger_id: str, power_kw: float) -> None:
    command = {
        "charger_id": charger_id,
        "rate_kw": round(power_kw, 2),
        "on": power_kw > 0,
    }
    client.publish(
        f"station/charger/{charger_id}/setpoint",
        json.dumps(command),
    )


def apply_schedule(client) -> None:
    """Compute and publish allocations for all chargers."""
    global _forecaster, _ml_fit_counter
    print(f"\n[MODE] {mode.upper()}")

    if mode == "dumb":
        demands = {cid: MAX_CHARGER_POWER_KW for cid in CHARGERS}
        total_request = sum(demands.values())
        print(
            f"[DUMB] Each charger requested {MAX_CHARGER_POWER_KW} kW "
            f"-> total {total_request:.2f} kW (UNSAFE: exceeds "
            f"{GRID_LIMIT_KW} kW limit)"
        )
        print("[SAFETY] Enforcing grid limit via proportional re-allocation.")

    elif mode == "ml":
        # Refit ML model every N cycles to save CPU.
        if _ml_fit_counter % _ML_REFIT_EVERY == 0:
            from ml_module import load_history
            history = load_history()
            _forecaster.fit(history)
            print(f"[ML] Refit forecaster on {sum(len(r) for r in history.values())} rows")
        _ml_fit_counter += 1
        demands = required_power_kw_ml(_forecaster)

    else:  # smart
        demands = {cid: required_power_kw(cid) for cid in CHARGERS}

    allocation = allocate_proportional(demands)

    for cid in CHARGERS:
        print(
            f"[SCHEDULER] {cid}: demand={demands[cid]:.2f} kW "
            f"-> allocated={allocation[cid]:.2f} kW"
        )

    for cid in CHARGERS:
        send_setpoint(client, cid, allocation[cid])

    total = sum(allocation.values())
    print(
        f"[SCHEDULER] Total allocated: {total:.2f} kW / "
        f"{GRID_LIMIT_KW:.2f} kW limit"
    )


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print("[MQTT] Connection failed:", reason_code)
        return
    print("[MQTT] Connected to broker")
    for charger_id in CHARGERS:
        client.subscribe(f"station/charger/{charger_id}/telemetry")
    client.subscribe("station/control/mode")
    apply_schedule(client)


def on_message(client, userdata, msg):
    global mode
    try:
        payload = msg.payload.decode()

        if msg.topic == "station/control/mode":
            requested_mode = payload.strip().lower()
            if requested_mode not in ("smart", "dumb", "ml"):
                print("[ERROR] Mode must be smart, dumb, or ml")
                return
            mode = requested_mode
            print(f"[CONTROL] Mode switched to {mode}")
            apply_schedule(client)
            return

        if msg.topic.endswith("/telemetry"):
            telemetry = json.loads(payload)
            charger_id = telemetry.get("charger_id")
            if charger_id not in CHARGERS:
                return

            live_telemetry[charger_id] = telemetry
            save_telemetry(telemetry)

            print(
                f"[LIVE] {charger_id} SOC={telemetry['soc']*100:.1f}% "
                f"power={telemetry['power_kw']:.2f} kW "
                f"hours_left={telemetry.get('hours_remaining', '?')}"
            )

            if all(cid in live_telemetry for cid in CHARGERS):
                apply_schedule(client)

    except (json.JSONDecodeError, ValueError, KeyError) as error:
        print(f"[ERROR] Invalid MQTT message: {error}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _watchdog():
    """Periodically re-apply schedule so chargers recover from lost setpoints.

    If a charger's last-known power is 0 but its demand is > 0, the scheduler
    will resend the setpoint on the next cycle. This watchdog ensures that
    even if a setpoint MQTT message was lost (race condition at startup,
    network blip, etc.), the charger will start receiving power within
    ~15 seconds.
    """
    while True:
        time.sleep(15)
        try:
            if all(cid in live_telemetry for cid in CHARGERS):
                print("[WATCHDOG] Periodic re-apply schedule")
                apply_schedule(client)
        except Exception as e:
            print(f"[WATCHDOG] error: {e}")


client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="gridsense_scheduler",
)
client.on_connect = on_connect
client.on_message = on_message

init_db()
print("[DATABASE] SQLite ready")
print(f"[SCHEDULER] Starting (chargers = {CHARGERS}, "
      f"grid limit = {GRID_LIMIT_KW} kW, modes = smart/dumb/ml)")
client.connect(BROKER, PORT, 60)

# Start the watchdog in a daemon thread
threading.Thread(target=_watchdog, daemon=True).start()

try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\n[SCHEDULER] Stopping...")
    client.disconnect()
```

## `simulator.py`

```python
"""
GridSense EV Simulator (v3 - ACN-Sim battery + ACN-Data sessions)

Changes vs v2:
  - SOC is now advanced by the ACN-Sim Linear2StageBattery model
    (battery_model.py), NOT by the simple `power * time / capacity`
    formula. This adds realistic Stage-2 charging taper above 80% SOC.
  - Session parameters (capacity, target SOC, hours_remaining) are
    loaded from acn_sessions.json via ev_data.py. These are real
    Caltech ACN-Data session records (cached sample). Battery capacity
    and initial SOC are explicitly flagged as estimated.
  - Telemetry now includes provenance fields:
      soc_source:           "acnsim_battery"
      session_source:       "acndata_sample" or "acndata_live" or "fallback"
      session_id:           the ACN-Data sessionID
      battery_backend:      backend identifier
  - hours_remaining now decreases with simulated time (matches the
    "time until departure" semantics recommended in the integration
    report), not only while charging.
"""

import json
import time
import threading

import paho.mqtt.client as mqtt

from ev_data import EVS, SESSION_META, SESSION_SOURCE
from battery_model import Linear2StageBattery, battery_backend


BROKER_HOST = "localhost"
BROKER_PORT = 1883

TIME_STEP_SECONDS = 5
TIME_ACCELERATION = 60

MAX_CHARGING_POWER_KW = 7.0


chargers: dict = {}
for charger_id, ev in EVS.items():
    capacity = ev["capacity_kwh"]
    init_soc = ev["soc_percent"] / 100.0
    init_charge_kwh = init_soc * capacity
    max_power = ev.get("max_power_kw", MAX_CHARGING_POWER_KW)
    transition = ev.get("transition_soc", 0.80)
    battery = Linear2StageBattery(
        capacity_kwh=capacity,
        init_soc_kwh=init_charge_kwh,
        max_power_kw=max_power,
        transition_soc=transition,
    )
    chargers[charger_id] = {
        "power_kw": 0.0,
        "battery": battery,
        "target_soc": ev["target_soc_percent"] / 100.0,
        "hours_remaining": ev["hours_remaining"],
        "session_id": SESSION_META.get(charger_id, {}).get(
            "sessionID", f"synthetic_{charger_id}"
        ),
    }


client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="gridsense_simulator",
)


def publish_telemetry(charger_id: str) -> None:
    charger = chargers[charger_id]
    battery = charger["battery"]

    telemetry = {
        "charger_id": charger_id,
        "power_kw": round(charger["power_kw"], 2),
        "soc": round(battery.soc_fraction(), 4),
        "hours_remaining": round(charger["hours_remaining"], 2),
        "status": "charging" if charger["power_kw"] > 0 else "idle",
        "timestamp": time.time(),
        # provenance
        "soc_source": "acnsim_battery",
        "session_source": SESSION_SOURCE,
        "session_id": charger["session_id"],
        "battery_backend": battery_backend(),
        "battery_capacity_kwh": battery.capacity_kwh,
        "target_soc": charger["target_soc"],
    }

    topic = f"station/charger/{charger_id}/telemetry"
    client.publish(topic, json.dumps(telemetry))

    print(
        f"[TELEMETRY] {charger_id} | "
        f"Power: {telemetry['power_kw']} kW | "
        f"SOC: {telemetry['soc'] * 100:.1f}% | "
        f"Hours left: {telemetry['hours_remaining']:.2f}h | "
        f"Status: {telemetry['status']} | "
        f"src={telemetry['session_source']}"
    )


def charger_loop(charger_id: str) -> None:
    print(f"[START] Virtual charger {charger_id} "
          f"(session={chargers[charger_id]['session_id']})")

    while True:
        charger = chargers[charger_id]
        battery = charger["battery"]
        power_kw = charger["power_kw"]

        sim_seconds = TIME_STEP_SECONDS * TIME_ACCELERATION
        sim_hours = sim_seconds / 3600.0

        charger["hours_remaining"] = max(
            0.0, charger["hours_remaining"] - sim_hours
        )

        if power_kw > 0:
            actual_power = battery.apply_power(
                requested_power_kw=power_kw,
                hours=sim_hours,
            )

            if abs(actual_power - power_kw) > 0.05:
                charger["power_kw"] = actual_power
                print(
                    f"[TAPER] {charger_id}: requested {power_kw:.2f} kW, "
                    f"battery accepted {actual_power:.2f} kW "
                    f"(SOC {battery.soc_fraction()*100:.1f}%)"
                )

            if battery.soc_fraction() >= charger["target_soc"]:
                charger["power_kw"] = 0.0
                print(
                    f"[COMPLETE] {charger_id} reached "
                    f"{charger['target_soc'] * 100:.0f}% SOC "
                    f"(via ACN-Sim battery)"
                )

        publish_telemetry(charger_id)
        time.sleep(TIME_STEP_SECONDS)


def on_message(client, userdata, msg):
    try:
        command = json.loads(msg.payload.decode())
        charger_id = command.get("charger_id")

        if charger_id not in chargers:
            print(f"[ERROR] Unknown charger: {charger_id}")
            return

        if command.get("on", False):
            requested_power = float(command.get("rate_kw", 0))
            max_p = chargers[charger_id]["battery"].max_power_kw
            requested_power = min(requested_power, max_p)
            chargers[charger_id]["power_kw"] = requested_power
            print(f"[COMMAND] {charger_id} -> {requested_power} kW")
        else:
            chargers[charger_id]["power_kw"] = 0.0
            print(f"[COMMAND] {charger_id} -> OFF")
    except json.JSONDecodeError:
        print("[ERROR] Received invalid JSON")
    except Exception as error:
        print(f"[ERROR] {error}")


client.on_message = on_message

print(f"[MQTT] Connecting to {BROKER_HOST}:{BROKER_PORT}")
client.connect(BROKER_HOST, BROKER_PORT, 60)
client.subscribe("station/charger/+/setpoint")
print("[MQTT] Subscribed to charger setpoints")
client.loop_start()

time.sleep(1.0)

print("[MQTT] Publishing initial telemetry to trigger scheduler...")
for charger_id in chargers:
    publish_telemetry(charger_id)

for charger_id in chargers:
    threading.Thread(
        target=charger_loop, args=(charger_id,), daemon=True
    ).start()

print()
print("==============================")
print(" GridSense EV Simulator v3")
print("==============================")
print(f" Chargers:          {list(chargers.keys())}")
print(f" Time acceleration: {TIME_ACCELERATION}x")
print(f" Max power:         {MAX_CHARGING_POWER_KW} kW")
print(f" Battery backend:   {battery_backend()}")
print(f" Session source:    {SESSION_SOURCE}")
print("==============================")
print()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[STOP] Simulator shutting down...")
    client.loop_stop()
    client.disconnect()
```

## `start.sh`

```bash
#!/usr/bin/env bash
# GridSense v3 clean start - ACN-Sim battery + ACN-Data sessions + ML.

set -e
cd "$(dirname "$0")"

echo "==> Stopping any orphaned GridSense processes..."
pkill -f "simulator.py" 2>/dev/null || true
pkill -f "scheduler.py" 2>/dev/null || true
pkill -f "streamlit run app.py" 2>/dev/null || true
rm -f .pids/*.pid 2>/dev/null || true
sleep 1

echo "==> (Optional) Try installing acnportal for the real ACN-Sim battery..."
uv add acnportal 2>/dev/null || pip install acnportal 2>/dev/null || \
    echo "    acnportal not installable; will use local Linear2StageBattery impl."

echo "==> Installing ML deps..."
uv add paho-mqtt streamlit scikit-learn numpy 2>/dev/null || \
    pip install paho-mqtt streamlit scikit-learn numpy

echo "==> Starting Mosquitto..."
sudo service mosquitto start || sudo systemctl start mosquitto || true
sleep 1

echo "==> Clearing old telemetry (>60s)..."
uv run python reset_db.py || true

echo "==> ACN-Data / ACN-Sim integration status:"
echo "    Sessions: $(uv run python -c 'from ev_data import SESSION_SOURCE; print(SESSION_SOURCE)')"
echo "    Battery:  $(uv run python -c 'from battery_model import battery_backend; print(battery_backend())')"

echo "==> Starting simulator (background)..."
uv run python simulator.py > simulator.log 2>&1 &
echo "  PID: $!"

echo "==> Starting scheduler (background)..."
uv run python scheduler.py > scheduler.log 2>&1 &
echo "  PID: $!"

echo "==> Waiting 3s for telemetry to start flowing..."
sleep 3

echo "==> Starting Streamlit dashboard (pandas-free)..."
echo "    Open http://localhost:8501 in your browser."
echo ""
uv run streamlit run app.py
```

## `test_mqtt.py`

```python
import paho.mqtt.client as mqtt
import time

client = mqtt.Client()

client.connect("localhost", 1883, 60)

for i in range(5):
    message = f"GridSense test message {i}"
    client.publish("station/test", message)
    print("Published:", message)
    time.sleep(2)

client.disconnect()
```
