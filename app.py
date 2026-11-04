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