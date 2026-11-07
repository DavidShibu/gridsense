"""Owns a complete local test stack; ports 1880/1883/8765 must be free."""
import json
import argparse
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--synthetic-only', action='store_true')
parser.add_argument('--mock-acn', action='store_true', help='Exercise real-source processing with deterministic ACN fixtures, no external data access')
args = parser.parse_args()
synthetic_only = args.synthetic_only or (not args.mock_acn and not os.environ.get('ACN_DATA_TOKEN'))
sensor_script = 'tests/mock_acn_sender.py' if args.mock_acn else 'simulator.py'
sensor_flags = ['--synthetic-only'] if synthetic_only else []
workers, handles, acks, states = [], [], [], []
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


def start(args, name, cwd=ROOT):
    handle = open(ROOT/f'{name}.log','w')
    handles.append(handle)
    process = subprocess.Popen(args,cwd=cwd,stdout=handle,stderr=subprocess.STDOUT)
    workers.append(process)
    return process


def wait_http(url, timeout=30):
    deadline = time.time()+timeout
    while time.time()<deadline:
        try:
            with urllib.request.urlopen(url,timeout=2) as response:
                return response.read()
        except OSError:
            time.sleep(.5)
    raise AssertionError('HTTP startup timed out: '+url)


def on_message(client, userdata, message):
    data = json.loads(message.payload)
    if message.topic=='ev/ack':
        acks.append(data)
    elif data.get('kind') != 'history':
        states.append(data)


try:
    for port in (1880, 1883, 8765):
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1',port)) == 0:
                raise RuntimeError(f'Stop the existing project before integration testing: port {port} is busy')
    start(['node','node-red/demo-broker.cjs'],'test-broker')
    service=start([sys.executable,'station_service.py'],'test-service')
    start(['node','node_modules/node-red/red.js','--userDir','.','--settings','settings.js','flows.json'],'test-nodered',ROOT/'node-red')
    wait_http('http://127.0.0.1:8765/health')
    wait_http('http://127.0.0.1:1880/dashboard/station')
    time.sleep(2)
    subprocess.run([sys.executable,sensor_script,'--history',*sensor_flags],cwd=ROOT,check=True,timeout=360)
    deadline=time.time()+20
    while time.time()<deadline:
        health=json.loads(wait_http('http://127.0.0.1:8765/health'))
        if health['active_history_rows']>=432:
            break
        time.sleep(.5)
    assert health['active_history_rows']>=432, 'History did not pass through Node-RED into SQLite'
    if synthetic_only:
        assert health['data_source']=='synthetic-fallback'
    if args.mock_acn:
        assert health['data_source']=='acn-data-caltech'
    print('History committed through MQTT/Node-RED:',health['history_rows'],flush=True)
    with open(ROOT/'training.log','w') as training_log:
        subprocess.run([sys.executable,'ml_train.py'],cwd=ROOT,stdout=training_log,stderr=subprocess.STDOUT,check=True,timeout=180)
    report=json.loads((ROOT/'artifacts/ml_comparison.json').read_text())
    assert len(report['models'])==5
    # Models are now startup-only; reload our own service after offline training.
    service.terminate()
    service.wait(timeout=10)
    start([sys.executable,'station_service.py'],'test-service-trained')
    wait_http('http://127.0.0.1:8765/health')
    print('Trained five models; selected:',report['selected_model'],flush=True)
    client.on_message=on_message
    client.connect('127.0.0.1',1883)
    client.subscribe('ev/ack',qos=1)
    client.subscribe('ev/telemetry',qos=1)
    client.loop_start()
    start([sys.executable,sensor_script,*sensor_flags],'test-simulator')
    deadline=time.time()+40
    while time.time()<deadline:
        if sum(a['accepted'] for a in acks)>=5 and any(s['applied_sequence']>=0 and s['load_kw']>1 for s in states):
            break
        time.sleep(.5)
    assert sum(a['accepted'] for a in acks)>=5, 'Insufficient accepted actuator plans'
    assert any(s['applied_sequence']>=0 and s['load_kw']>1 for s in states)
    assert max(s['load_kw'] for s in states)<=9.5+1e-6
    time.sleep(1)
    conn=sqlite3.connect(ROOT/'station.db')
    try:
        run=states[-1]['run_id']
        count=conn.execute('SELECT count(*) FROM cycles WHERE run_id=?',(run,)).fetchone()[0]
        ack_count=conn.execute('SELECT count(*) FROM actuator_acks WHERE run_id=?',(run,)).fetchone()[0]
        decision=json.loads(conn.execute('SELECT decision FROM cycles WHERE run_id=? AND decision IS NOT NULL ORDER BY sequence DESC LIMIT 1',(run,)).fetchone()[0])
    finally:
        conn.close()
    assert ack_count>0
    assert decision['model']==report['selected_model']
    assert report['data_source']==health['data_source']
    result={'accepted_commands':sum(a['accepted'] for a in acks),'stored_cycles':count,
            'stored_acknowledgements':ack_count,'history_rows':health['history_rows'],
            'dashboard_http':200,'selected_model':decision['model'], 'data_source':report['data_source'],
            'acn_fixture_test':args.mock_acn,
            'max_observed_load_kw':max(s['load_kw'] for s in states),
            'mean_response_ms':sum(a['response_ms'] for a in acks if a['accepted'])/sum(a['accepted'] for a in acks)}
    times=sorted(a['response_ms'] for a in acks if a['accepted'])
    result['p95_response_ms']=times[min(len(times)-1,int(.95*len(times)))]
    result['mean_inference_ms']=sum(a['inference_ms'] for a in acks if a['accepted'])/len(times)
    output = 'live_check_acn_mock.json' if args.mock_acn else 'live_check.json'
    (ROOT/'artifacts'/output).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
finally:
    client.disconnect()
    client.loop_stop()
    for worker in reversed(workers):
        if worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=10)
    for handle in handles:
        handle.close()
