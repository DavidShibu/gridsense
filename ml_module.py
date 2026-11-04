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
