"""Idempotently install Dashboard 2 widgets into the existing flow. Stop Node-RED first."""
import json
from pathlib import Path

ROOT = Path(__file__).parent


def upgrade():
    path = ROOT / 'node-red/flows.json'
    backup = path.with_name('flows.before-upgrades.json')
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    nodes = {n['id']: n for n in json.loads(path.read_text(encoding='utf-8'))}

    def group(id, name, order):
        nodes[id] = {**nodes['group'], 'id': id, 'name': name, 'order': order, 'showTitle': True}

    def function(id, name, code, wires, outputs=1):
        nodes[id] = dict(id=id, type='function', z='station', name=name, func=code,
                         outputs=outputs, x=650, y=500 + len(nodes)*5, wires=wires)

    def template(id, name, file, group_id, order):
        nodes[id] = {**nodes['live-dashboard'], 'id': id, 'name': name, 'group': group_id,
                     'order': order, 'format': (ROOT/'node-red/templates'/file).read_text(encoding='utf-8'),
                     'passthru': False, 'wires': [[]]}

    nodes['page'].update(name='Station overview', className='gs-page')
    nodes['group'].update(name='Station overview', className='gs-section', order=1, showTitle=False)
    template('live-dashboard', 'Station overview and fleet', 'station-overview.vue', 'group', 1)
    group('soc-group', 'Battery levels', 3)
    group('charts-group', 'Energy & pricing', 4)
    group('alerts-group', 'Station alerts', 2)
    group('ml-group', 'ML and control evaluation', 5)
    nodes['theme']['colors'].update(primary='#176b50', surface='#ffffff', bgPage='#f1f6f3', groupBg='#ffffff', groupOutline='#dce7e4')
    nodes['theme']['sizes'].update(pagePadding='24px', groupGap='20px', groupBorderRadius='16px', widgetGap='16px')
    nodes['live-filter']['wires'] = [['live-dashboard', 'soc-router', 'load-series', 'price-history']]
    function('soc-router', 'SoC 0–100% per EV', '''const p=msg.payload;
return ['EV1','EV2','EV3','EV4','EV5','EV6'].map(id => {
  const e=p.vehicles.find(v=>v.id===id);
  if (!e || !Number.isFinite(e.soc)) return {payload:0, ui_update:{label:id+' — unavailable',color:'#94a3b8'}};
  return {payload:Math.max(0,Math.min(100,e.soc*100)),
    ui_update:{label:`${id} · ${e.status} · target ${(e.target*100).toFixed(0)}%`,
      color:e.soc>=e.target-0.001?'#16a34a':e.status==='charging'?'#2563eb':'#d97706'}};
});''', [[f'soc-EV{i}'] for i in range(1, 7)], outputs=6)
    for i in range(1, 7):
        nodes[f'soc-EV{i}'] = dict(id=f'soc-EV{i}', type='ui-progress', z='station',
            group='soc-group', name=f'EV{i} SoC', label=f'EV{i}', order=i,
            width=6, height=1, color='#2563eb', className='', x=950, y=450+i*45, wires=[])
    function('load-series', 'Grid load / limit / demand estimate', '''const p=msg.payload;
if (!Number.isFinite(p.timestamp)||!Number.isFinite(p.load_kw)) return null;
const previous=context.get('last');
if(previous?.run===p.run_id && p.sequence<=previous.seq) return null;
context.set('last',{run:p.run_id,seq:p.sequence});
const rows=[];
if(previous?.run!==p.run_id) rows.push({payload:[]});
for(const [topic,value] of [['Measured grid load',p.load_kw],['Operating limit',p.operating_limit_kw],
  ['Unmanaged demand estimate',p.unmanaged_demand_estimate_kw]]) {
  if(Number.isFinite(value)) rows.push({topic,payload:{x:p.timestamp*1000,y:value}});
}
return [rows];''', [['grid-load-chart']])
    nodes['grid-load-chart'] = dict(id='grid-load-chart', type='ui-chart', z='station',
        group='charts-group', name='Grid Load over Time', label='Grid Load over Time (kW)',
        order=1, width=12, height=6, chartType='line', category='topic', categoryType='msg',
        xAxisProperty='x', xAxisPropertyType='property', xAxisType='time',
        xAxisFormat='{HH}:{mm}:{ss}', xAxisFormatType='custom', xAxisLabel='Wall-clock time',
        yAxisProperty='y', yAxisPropertyType='property', yAxisLabel='Grid load (kW)',
        ymin='0', ymax='', action='append', stackSeries=False, pointRadius=0, pointShape='circle',
        showLegend=True, removeOlder=12, removeOlderUnit='60', removeOlderPoints='1080',
        colors=['#166534', '#dc2626', '#94a3b8'], interpolation='linear', x=950, y=800, wires=[[]])
    function('price-history', 'Bounded tariff/load history', '''const p=msg.payload;
if(![p.hour,p.price_per_kwh,p.charging_load_kw].every(Number.isFinite)) return null;
let state=context.get('history');
if(!state || state.run!==p.run_id) state={run:p.run_id,seq:-1,points:[]};
if(p.sequence<=state.seq) return null;
state.seq=p.sequence;
state.points.push({hour:p.hour,price:p.price_per_kwh,load:p.charging_load_kw});
state.points=state.points.slice(-360);
context.set('history',state);
return {payload:{points:state.points}};''', [['price-load-chart']])
    template('price-load-chart', 'Price vs Charging Load (two axes)', 'price-load.vue', 'charts-group', 2)
    template('alerts-panel', 'Severity-coloured alerts', 'alerts.vue', 'alerts-group', 1)
    template('dashboard', 'Five-model evaluation', 'ml-comparison.vue', 'ml-group', 1)
    nodes['route']['wires'][0] = ['dashboard', 'alerts-panel']
    path.write_text(json.dumps(list(nodes.values()), indent=2, ensure_ascii=False), encoding='utf-8')
    print('Updated', path)


if __name__ == '__main__':
    upgrade()
