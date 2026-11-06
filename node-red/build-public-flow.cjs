// Derive a public-broker flow without changing the local/private demo flow.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function buildPublicFlow(profile, base) {
  const prefix = profile.topic_prefix;
  if (typeof prefix !== 'string' || !prefix || /^[\/]|[\/]$|[+#\x00]/.test(prefix)) {
    throw new Error('Invalid MQTT topic prefix');
  }
  const flows = JSON.parse(JSON.stringify(base));
  const nodes = Object.fromEntries(flows.map(n => [n.id, n]));
  // New ID avoids inheriting any saved private-broker credentials.
  Object.assign(nodes.broker, {id: 'public-broker', name: 'EMQX public broker (TLS)',
    broker: profile.host, port: String(profile.port), usetls: true, tls: 'public-tls',
    clientid: 'gs_project_' + crypto.randomBytes(8).toString('hex')});
  delete nodes.broker.credentials;
  for (const node of flows) if (node.broker === 'broker') node.broker = 'public-broker';
  for (const [id, suffix] of [['sensor', 'telemetry'], ['actuator', 'actuator'], ['ack', 'ack']]) {
    nodes[id].topic = `${prefix}/${suffix}`;
  }
  flows.push({id: 'public-tls', type: 'tls-config', name: 'Verify EMQX certificate',
    cert: '', key: '', ca: '', certname: '', keyname: '', caname: '',
    servername: profile.host, verifyservercert: true, alpnprotocol: ''});
  nodes.station.label = 'GridSense public MQTT loop';
  nodes.station.info = `Public MQTT over verified TLS; topic prefix ${prefix}. Synthetic demo data only.`;
  return flows;
}

if (require.main === module) {
  const profile = JSON.parse(fs.readFileSync(path.join(__dirname, '../mqtt-public.json'), 'utf8'));
  const base = JSON.parse(fs.readFileSync(path.join(__dirname, 'flows.json'), 'utf8'));
  fs.writeFileSync(path.join(__dirname, 'flows.public.json'), JSON.stringify(buildPublicFlow(profile, base), null, 2));
  console.log(`Public MQTT: ${profile.host}:${profile.port}; topics ${profile.topic_prefix}/*`);
}
module.exports = {buildPublicFlow};
