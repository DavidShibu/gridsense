// Local demonstration broker; replace with Mosquitto for deployment if desired.
const broker = require('aedes')();
const server = require('net').createServer(broker.handle);
server.listen(1883, '127.0.0.1', () => console.log('MQTT demo broker on 127.0.0.1:1883'));
