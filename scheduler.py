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
