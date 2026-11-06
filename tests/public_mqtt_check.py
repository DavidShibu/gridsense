"""Exercise the real public TLS broker with synthetic data and isolated test topics.

Uses existing trained models; writes test cycles to station.db, not training data.
Requires free local ports 1880/8765. Does not start a local broker.
"""
import json
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]


def main():
    profile = json.loads((ROOT/'mqtt-public.json').read_text())
    prefix = profile['topic_prefix'] + '/check-' + uuid.uuid4().hex[:12]
    workers, handles, states, acks = [], [], [], []
    subscribed = threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='gs_check_'+uuid.uuid4().hex[:12])
    client.tls_set_context(ssl.create_default_context())

    def start(args, name, cwd=ROOT):
        handle = open(ROOT/f'{name}.log', 'w')
        handles.append(handle)
        worker = subprocess.Popen(args, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        workers.append(worker)

    def wait_http(url):
        deadline = time.monotonic()+40
        while time.monotonic() < deadline:
            if any(w.poll() is not None for w in workers):
                raise RuntimeError('Test service exited; inspect public-check-*.log')
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    return response.status
            except OSError:
                time.sleep(.5)
        raise RuntimeError('Service startup timed out: '+url)

    def connected(c, userdata, flags, reason, properties):
        if reason == 0:
            c.subscribe([(prefix+'/telemetry', 1), (prefix+'/ack', 1)])

    def on_subscribe(c, userdata, mid, reasons, properties):
        if all(not reason.is_failure for reason in reasons):
            subscribed.set()

    def received(c, userdata, message):
        data = json.loads(message.payload)
        (acks if message.topic.endswith('/ack') else states).append(data)

    client.on_connect, client.on_subscribe, client.on_message = connected, on_subscribe, received
    try:
        for port in (1880, 8765):
            with socket.socket() as probe:
                probe.settimeout(1)
                if probe.connect_ex(('127.0.0.1', port)) == 0:
                    raise RuntimeError(f'Stop the existing project first; port {port} is busy')
        # This generated flow uses the actual app wiring and the test's isolated topics.
        subprocess.run(['node', '-e',
            "const fs=require('fs');const {buildPublicFlow}=require('./node-red/build-public-flow.cjs');"
            "const p=JSON.parse(fs.readFileSync('mqtt-public.json'));p.topic_prefix=process.argv[1];"
            "fs.writeFileSync('node-red/flows.public-check.json',JSON.stringify(buildPublicFlow(p,JSON.parse(fs.readFileSync('node-red/flows.json')))));",
            prefix], cwd=ROOT, check=True)
        client.connect(profile['host'], profile['port'], 60)
        client.loop_start()
        if not subscribed.wait(25):
            raise RuntimeError('Public broker did not accept observer subscriptions')
        print('Public MQTT TLS connection and subscriptions confirmed.', flush=True)
        start([sys.executable, 'station_service.py'], 'public-check-service')
        wait_http('http://127.0.0.1:8765/health')
        start(['node', 'node_modules/node-red/red.js', '--userDir', '.', '--settings', 'settings.js',
               'flows.public-check.json'], 'public-check-nodered', ROOT/'node-red')
        dashboard = wait_http('http://127.0.0.1:1880/dashboard/station')
        start([sys.executable, 'simulator.py', '--broker-host', profile['host'], '--broker-port',
               str(profile['port']), '--tls', '--topic-prefix', prefix], 'public-check-sensor')
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            if any(w.poll() is not None for w in workers):
                raise RuntimeError('A test worker exited; inspect public-check-*.log')
            if sum(a.get('accepted', False) for a in acks) >= 5 and any(s['applied_sequence'] >= 0 for s in states):
                break
            time.sleep(.5)
        accepted = [a for a in acks if a.get('accepted')]
        assert len(accepted) >= 5, 'Fewer than five accepted public-MQTT commands'
        assert any(s['applied_sequence'] >= 0 for s in states), 'Actuator effects not visible in telemetry'
        assert max(s['load_kw'] for s in states) <= 9.5+1e-6
        time.sleep(2)
        run = states[-1]['run_id']
        with sqlite3.connect(ROOT/'station.db') as db:
            stored = db.execute('SELECT count(*) FROM cycles WHERE run_id=?', (run,)).fetchone()[0]
            stored_acks = db.execute('SELECT count(*) FROM actuator_acks WHERE run_id=?', (run,)).fetchone()[0]
            row = db.execute('SELECT decision FROM cycles WHERE run_id=? AND decision IS NOT NULL ORDER BY sequence DESC LIMIT 1', (run,)).fetchone()
        assert stored >= 5 and stored_acks >= 5 and row
        decision = json.loads(row[0])
        assert decision['model'] != 'untrained_safe_rules'
        result = {'broker': profile['host'], 'port': profile['port'], 'tls_verified': True,
                  'test_scope': 'Local clients using the real internet broker; not two physical laptops',
                  'topic_prefix': prefix, 'accepted_commands': len(accepted), 'stored_cycles': stored,
                  'stored_acknowledgements': stored_acks, 'selected_model': decision['model'],
                  'dashboard_http': dashboard, 'max_observed_load_kw': max(s['load_kw'] for s in states),
                  'mean_response_ms': sum(a['response_ms'] for a in accepted)/len(accepted)}
        (ROOT/'artifacts/public_mqtt_check.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)
    finally:
        client.disconnect()
        client.loop_stop()
        for worker in reversed(workers):
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=10)
        for handle in handles:
            handle.close()


if __name__ == '__main__':
    main()
