// Local demonstration broker; replace with Mosquitto for deployment if desired.
const broker = require('aedes')();
const server = require('net').createServer(broker.handle);
const host = process.argv.includes('--lan') ? '0.0.0.0' : '127.0.0.1';
server.listen(1883, host, () => console.log(`MQTT demo broker on ${host}:1883`));
