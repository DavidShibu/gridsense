// Validate real flow Function code and compile Dashboard Vue templates locally.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const {parse, compileScript, compileTemplate} = require('@vue/compiler-sfc');
const flows = JSON.parse(fs.readFileSync(__dirname + '/flows.json', 'utf8'));
const nodes = Object.fromEntries(flows.map(n=>[n.id,n]));
for (const name of ['station-overview','alerts','ml-comparison','price-load']) {
  const source=fs.readFileSync(`${__dirname}/templates/${name}.vue`,'utf8');
  const {descriptor,errors}=parse(source);
  assert.equal(errors.length,0);
  compileScript(descriptor,{id:name});
  const result=compileTemplate({source:descriptor.template.content,filename:name+'.vue',id:name});
  assert.deepEqual(result.errors,[]);
}
function run(id,payload,store={}) {
  const context={get:key=>store[key],set:(key,value)=>{store[key]=value}};
  const node={error:()=>{},warn:()=>{}};
  return vm.runInNewContext(`(function(){${nodes[id].func}})()`,{msg:{payload},context,node});
}
const p={kind:'telemetry',run_id:'test',sequence:1,timestamp:100,hour:16,
  load_kw:8,operating_limit_kw:9.5,unmanaged_demand_estimate_kw:15,
  price_per_kwh:12,charging_load_kw:7,vehicles:[{id:'EV1',soc:.55,target:.8,status:'charging'}]};
const bars=run('soc-router',p);
assert.equal(bars.length,6);
assert.ok(Math.abs(bars[0].payload-55)<1e-10);
assert.match(bars[1].ui_update.label,/unavailable/);
const store={};
const chart=run('load-series',p,store)[0];
assert.equal(chart.length,4); // reset and three series
assert.equal(chart[1].payload.x,100000);
assert.equal(run('load-series',p,store),null);
const history={};
for(let i=0;i<400;i++) run('price-history',{...p,sequence:i,hour:16+i/30},history);
assert.equal(history.history.points.length,360);
run('price-history',{...p,run_id:'new'},history);
assert.equal(history.history.points.length,1);
assert.equal(flows.filter(n=>n.type==='ui-progress').length,6);
assert.equal(nodes.sensor.topic,'ev/telemetry');
assert.equal(nodes.actuator.topic,'ev/actuator');
assert.equal(nodes.ack.topic,'ev/ack');
const ids=new Set(flows.map(n=>n.id));
for(const node of flows) for(const output of node.wires||[]) for(const id of output) assert.ok(ids.has(id),id);
console.log('Dashboard templates compile; SoC, chart mapping, deduplication, bounded history and wiring pass.');
const {buildPublicFlow} = require('./build-public-flow.cjs');
const profile = JSON.parse(fs.readFileSync(__dirname + '/../mqtt-public.json', 'utf8'));
const publicNodes = Object.fromEntries(buildPublicFlow(profile, flows).map(n => [n.id, n]));
assert.equal(publicNodes['public-broker'].usetls, true);
assert.equal(publicNodes['public-tls'].verifyservercert, true);
assert.equal(publicNodes['public-tls'].servername, profile.host);
for (const [id, suffix] of [['sensor','telemetry'], ['actuator','actuator'], ['ack','ack']]) {
  assert.equal(publicNodes[id].topic, `${profile.topic_prefix}/${suffix}`);
  assert.equal(publicNodes[id].broker, 'public-broker');
}
assert.equal(nodes.sensor.topic, 'ev/telemetry'); // Base flow remains unchanged.
assert.notEqual(buildPublicFlow(profile, flows).find(n=>n.id==='public-broker').clientid, publicNodes['public-broker'].clientid);
console.log('Public profile: matching topics, verified TLS, unique client IDs and local-flow isolation pass.');
