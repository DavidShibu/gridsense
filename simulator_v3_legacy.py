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