"""Physical sensor layer + simulated plant. Publishes only through MQTT.

--history replays synthetic historical sensor observations through ev/telemetry;
Node-RED persists them. This script never writes training data directly to DB.
"""
import argparse
import json
import os
import ssl
import getpass
import threading
import time
import uuid
import logging
from pathlib import Path
import paho.mqtt.client as mqtt
try:
    from .station_core import Station, real_or_synthetic_history, real_or_synthetic_vehicles, tou_demo_station
    from .actuator import Actuator
    from .tariff import telemetry_fields
except ImportError:
    from station_core import Station, real_or_synthetic_history, real_or_synthetic_vehicles, tou_demo_station
    from actuator import Actuator
    from tariff import telemetry_fields


def history_payload(synthetic_only=False):
    rows = real_or_synthetic_history(days=42, prefer_real=not synthetic_only)
    source = rows[0].get('source', 'synthetic-fallback') if rows else 'synthetic-fallback'
    days = max((r['day'] for r in rows), default=41)+1
    bins = [[0.0]*24 for _ in range(days)]
    for r in rows:
        bins[r['day']][r['hour']] += r['energy_kwh']
    return {'kind':'history','dataset':'acn-caltech-v1' if source == 'acn-data-caltech' else 'synthetic-history-v5','source':source,
            'samples':[{'day':d,'hour':h,'energy_kwh':value}
                       for d, row in enumerate(bins) for h,value in enumerate(row)]}


def configure_connection(client, args):
    if args.ca_cert and not args.tls:
        raise ValueError('--ca-cert requires --tls')
    if args.username and not args.tls:
        raise ValueError('Use --tls when sending MQTT login credentials')
    if args.tls:
        client.tls_set_context(ssl.create_default_context(cafile=args.ca_cert))
    if args.username:
        password = os.environ.get('MQTT_PASSWORD')
        if password is None:
            password = getpass.getpass('MQTT password: ')
        client.username_pw_set(args.username, password)


def apply_public_profile(args):
    profile = json.loads(Path(__file__).with_name('mqtt-public.json').read_text(encoding='utf-8'))
    args.broker_host = profile['host']
    args.broker_port = profile['port']
    args.topic_prefix = profile['topic_prefix']
    args.tls = True
    # Public mode must never forward credentials intended for a private broker.
    args.username = None


def validate_topic_prefix(prefix):
    if not prefix or prefix.startswith('/') or prefix.endswith('/') or any(c in prefix for c in ('+', '#', '\x00')):
        raise ValueError('Topic prefix must be nonempty, without wildcards or leading/trailing slash')
    return prefix


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument('--synthetic-only', action='store_true', help='Force deterministic offline data; do not fetch or use prepared ACN data')
    parser.add_argument('--public-broker', action='store_true', help='Use the shared mqtt-public.json profile with verified TLS and no credentials')
    parser.add_argument('--topic-prefix', default='ev', help='Shared MQTT topic prefix (default: ev for local/private mode)')
    parser.add_argument('--broker-host', default='127.0.0.1', help='MQTT broker address (project laptop LAN IP for two-laptop mode)')
    parser.add_argument('--broker-port', type=int, help='MQTT TCP port (default: 8883 with TLS, otherwise 1883)')
    parser.add_argument('--tls', action='store_true', help='Verify the cloud broker certificate and encrypt MQTT traffic')
    parser.add_argument('--ca-cert', help='Optional broker CA certificate PEM file')
    parser.add_argument('--username', default=os.environ.get('MQTT_USERNAME'), help='MQTT username; password is prompted or read from MQTT_PASSWORD')
    parser.add_argument('--history',action='store_true',help='Replay 42 historical days via MQTT for database training')
    parser.add_argument('--tou-demo', action='store_true', help='Feasible 16:00–24:00 tariff-shifting demo')
    args = parser.parse_args()
    try:
        if args.public_broker:
            apply_public_profile(args)
        validate_topic_prefix(args.topic_prefix)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    telemetry_topic = args.topic_prefix + '/telemetry'
    # Fetch history before opening MQTT so slow paginated downloads cannot leave
    # a partially initialized sensor connected. History mode never fetches vehicles twice.
    history = history_payload(args.synthetic_only) if args.history else None
    if args.tou_demo:
        station = tou_demo_station()
        station.data_source = 'synthetic-tou-demo'
    elif args.history:
        station = Station()
    else:
        station = Station(real_or_synthetic_vehicles(prefer_real=not args.synthetic_only))
        station.data_source = getattr(station.vehicles[0], 'data_source', 'synthetic-fallback')
        if station.data_source == 'acn-data-caltech':
            station.hour = min(v.arrival for v in station.vehicles)
            station.refresh()
    lock = threading.Lock()
    # The hardware rating remains 10 kW; Station enforces a 9.5 kW operating
    # ceiling including base load, independently of received command limits.
    run_id = str(uuid.uuid4())
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='gridsense_sensor_'+run_id[:8])
    try:
        configure_connection(client, args)
    except ValueError as exc:
        parser.error(str(exc))
    actuator = Actuator(station,run_id,lock,topic_prefix=args.topic_prefix)
    connected = threading.Event()
    connection_errors = []
    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            connection_errors.append(str(reason_code))
        else:
            actuator.on_connect(client, userdata, flags, reason_code, properties)
        connected.set()
    client.on_connect = on_connect
    client.on_message = actuator.on_message
    client.connect(args.broker_host,args.broker_port or (8883 if args.tls else 1883),60)
    client.loop_start()
    try:
        if not connected.wait(15):
            raise RuntimeError('MQTT connection acknowledgement timed out; check the broker address, TLS and network')
        if connection_errors:
            raise RuntimeError('MQTT connection rejected: ' + connection_errors[0])
        print(f'Connected to {args.broker_host}; publishing {telemetry_topic} and listening on {args.topic_prefix}/actuator.', flush=True)
        if args.history:
            receipt = client.publish(telemetry_topic,json.dumps(history),qos=1)
            receipt.wait_for_publish(timeout=10)
            if not receipt.is_published():
                raise RuntimeError('Broker did not acknowledge history publish')
            print(f"Published {len(history['samples'])} hourly observations; source={history['source']}. Check /health before training.")
            return
        while True:
            with lock:
                state = station.snapshot()
                state.update(telemetry_fields(state))
                state.update(kind='telemetry',run_id=run_id,timestamp=time.time())
            client.publish(telemetry_topic,json.dumps(state),qos=1)
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
