"""Physical sensor layer + simulated plant. Publishes only through MQTT.

--history replays synthetic historical sensor observations through ev/telemetry;
Node-RED persists them. This script never writes training data directly to DB.
"""
import argparse
import json
import threading
import time
import uuid
import paho.mqtt.client as mqtt
from station_core import Station, historical_sessions, tou_demo_station
from actuator import Actuator
from tariff import telemetry_fields


def history_payload():
    bins = [[0.0]*24 for _ in range(42)]
    for r in historical_sessions(days=42):
        bins[r['day']][r['hour']] += r['energy_kwh']
    return {'kind':'history','dataset':'synthetic-history-v5','source':'seeded_python_sensor_simulator',
            'samples':[{'day':d,'hour':h,'energy_kwh':value}
                       for d, row in enumerate(bins) for h,value in enumerate(row)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--history',action='store_true',help='Replay 42 historical days via MQTT for database training')
    parser.add_argument('--tou-demo', action='store_true', help='Feasible 16:00–24:00 tariff-shifting demo')
    args = parser.parse_args()
    station, lock = (tou_demo_station() if args.tou_demo else Station()), threading.Lock()
    # The hardware rating remains 10 kW; Station enforces a 9.5 kW operating
    # ceiling including base load, independently of received command limits.
    run_id = str(uuid.uuid4())
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='gridsense_sensor_'+run_id[:8])
    actuator = Actuator(station,run_id,lock)
    client.on_connect = actuator.on_connect
    client.on_message = actuator.on_message
    client.connect('127.0.0.1',1883,60)
    client.loop_start()
    try:
        if args.history:
            receipt = client.publish('ev/telemetry',json.dumps(history_payload()),qos=1)
            receipt.wait_for_publish(timeout=10)
            if not receipt.is_published():
                raise RuntimeError('Broker did not acknowledge history publish')
            print('Published 1008 historical hourly observations. Check /health for SQLite row count before training.')
            return
        while True:
            with lock:
                state = station.snapshot()
                state.update(telemetry_fields(state))
                state.update(kind='telemetry',run_id=run_id,timestamp=time.time())
            client.publish('ev/telemetry',json.dumps(state),qos=1)
            time.sleep(2)
            with lock:
                station.step(1/30)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == '__main__':
    main()
