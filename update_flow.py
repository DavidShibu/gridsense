"""Build the rubric flow from the existing Dashboard 2.0 configuration."""
import json
from pathlib import Path

path = Path(__file__).parent/'node-red/flows.json'
nodes = json.loads(path.read_text(encoding='utf-8'))
by_id = {n['id']:n for n in nodes}
by_id['station']['info'] = 'ev/telemetry splits immediately: A live Dashboard; B SQLite commit -> DB-only analytics/evaluation -> decision -> ev/actuator. ev/ack records control performance.'
by_id['sensor'].update(topic='ev/telemetry',wires=[['live-filter','request']])
by_id['request']['name'] = 'Path B: SQLite storage adapter'
by_id['analytics'].update(name='Commit telemetry/history to SQLite',url='http://127.0.0.1:8765/store',wires=[['stored']])
by_id['route']['func'] = "if(msg.statusCode !== 200 || !msg.payload.decision) {node.error('Decision failed',msg);return null;} return [msg,msg];"
by_id['actuator']['topic'] = 'ev/actuator'
by_id['ack'].update(topic='ev/ack',wires=[['debug','ack-store']])
by_id['command']['func'] = "msg.payload = JSON.stringify(msg.payload.decision); return msg;"
by_id['dashboard']['name'] = 'ML comparison and closed-loop metrics'
by_id['dashboard']['order'] = 2
by_id['dashboard']['format'] = '''<template><div v-if="msg?.payload?.decision" style="padding:16px">
<h2>ML, computational and closed-loop evaluation</h2>
<p>Selected: {{msg.payload.decision.model}} · Next-hour demand: {{msg.payload.decision.forecast_next_hour_kwh.toFixed(2)}} kWh</p>
<p>Prediction latency this cycle: {{msg.payload.decision.inference_ms.toFixed(3)}} ms</p>
<p>Classification = hourly energy ≥30 kWh; regression predicts kWh.</p>
<div style="overflow-x:auto"><table style="width:100%;text-align:left"><thead><tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>RMSE</th><th>MAE</th><th>R²</th><th>Train s</th><th>p95 ms</th><th>Memory bytes*</th><th>Size bytes</th></tr></thead>
<tbody><tr v-for="(m,name) in msg.payload.decision.performance.models" :key="name"><td>{{name}}</td><td>{{m.test.accuracy.toFixed(3)}}</td><td>{{m.test.precision.toFixed(3)}}</td><td>{{m.test.recall.toFixed(3)}}</td><td>{{m.test.f1.toFixed(3)}}</td><td>{{m.test.rmse_kwh.toFixed(2)}}</td><td>{{m.test.mae_kwh.toFixed(2)}}</td><td>{{m.test.r2.toFixed(3)}}</td><td>{{m.computational.training_seconds.toFixed(2)}}</td><td>{{m.computational.inference_p95_ms.toFixed(3)}}</td><td>{{m.computational.peak_traced_memory_bytes}}</td><td>{{m.computational.model_size_bytes}}</td></tr></tbody></table></div>
<p>*Peak tracked allocations during training, not total process memory. Metrics are from held-out synthetic days.</p>
<h3>Control performance (this run)</h3><p v-for="(value,key) in msg.payload.closed_loop" :key="key">{{key}}: {{value === null ? 'Not yet measurable' : value}}</p>
<h3>Decision</h3><p v-for="a in msg.payload.decision.assignments" :key="a.charger_id">{{a.charger_id}} → {{a.ev_id}}: {{a.rate_kw}} kW</p>
<p>Minimum assignment dwell: 6 simulated minutes; rate deadband: 0.25 kW. Safety/completion/departure override.</p>
<h3>Alerts</h3><p v-for="a in msg.payload.decision.alerts" :key="a">{{a}}</p>
</div><p v-else>Waiting for stored-data analytics… Live telemetry above is independent.</p></template>'''
new = [
 {'id':'live-filter','type':'function','z':'station','name':'Path A: live telemetry only','func':"return msg.payload.kind === 'history' ? null : msg;",'outputs':1,'x':390,'y':40,'wires':[['live-dashboard']]},
 {'id':'live-dashboard','type':'ui-template','z':'station','group':'group','name':'Direct real-time sensor display','order':1,'width':'12','height':'0','templateScope':'local','storeOutMessages':True,'passthru':False,'resendOnRefresh':True,'x':690,'y':40,'wires':[[]],
  'format':'''<template><div v-if="msg?.payload?.vehicles" style="padding:16px"><h2>GridSense live sensors — Path A</h2><p>Sensor timestamp: {{new Date(msg.payload.timestamp*1000).toLocaleTimeString()}} · Sequence {{msg.payload.sequence}} · Simulated hour {{msg.payload.hour.toFixed(2)}}</p><h3>Load {{msg.payload.load_kw.toFixed(2)}} / {{msg.payload.capacity_kw}} kW</h3><p>Applied command {{msg.payload.applied_sequence}} · {{msg.payload.source}}</p><table style="width:100%;text-align:left"><tr><th>EV</th><th>Status</th><th>Charger</th><th>SoC</th><th>Target</th><th>Arrival / deadline</th><th>kW</th><th>Remaining kWh</th></tr><tr v-for="e in msg.payload.vehicles" :key="e.id"><td>{{e.id}}</td><td>{{e.status}}</td><td>{{e.charger || '—'}}</td><td>{{(e.soc*100).toFixed(1)}}%</td><td>{{e.target*100}}%</td><td>{{e.arrival}} / {{e.departure}}</td><td>{{e.power_kw.toFixed(2)}}</td><td>{{e.remaining_kwh.toFixed(2)}}</td></tr></table><p>This panel updates directly from MQTT, even when analytics/storage is unavailable. Check the sensor timestamp for freshness.</p></div><p v-else>Waiting for ev/telemetry…</p></template>'''},
 {'id':'stored','type':'function','z':'station','name':'After commit: pass DB record key only','func':"if(msg.statusCode !== 200){node.error('SQLite write failed',msg);return null;} if(msg.payload.stored_history_rows !== undefined){node.warn('History committed: '+msg.payload.stored_history_rows);return null;} msg.headers={'content-type':'application/json'};return msg;",'outputs':1,'x':980,'y':130,'wires':[['db-decision']]},
 {'id':'db-decision','type':'http request','z':'station','name':'Read SQLite → ML/evaluation → decision','method':'POST','ret':'obj','paytoqs':'ignore','url':'http://127.0.0.1:8765/decide','x':990,'y':190,'wires':[['route']]},
 {'id':'ack-store','type':'http request','z':'station','name':'Persist actuator timing and switches','method':'POST','ret':'obj','paytoqs':'ignore','url':'http://127.0.0.1:8765/ack','x':580,'y':390,'wires':[[]]}
]
for node in new:
    by_id[node['id']] = node
path.write_text(json.dumps(list(by_id.values()),indent=2),encoding='utf-8')
from upgrade_dashboard import upgrade
upgrade()
