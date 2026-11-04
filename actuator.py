"""Actuator driver co-located with physical simulator; subscribes to ev/actuator.

It shares the simulated hardware state with simulator.py, so there is only one
authoritative station. It does not make scheduling decisions.
"""
import json
import time


class Actuator:
    def __init__(self, station, run_id, lock):
        self.station, self.run_id, self.lock = station, run_id, lock
        self.switch_count = 0
        self.rapid_switch_count = 0
        self.last_switch = {}

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe('ev/actuator', qos=1)

    def on_message(self, client, userdata, msg):
        try:
            command = json.loads(msg.payload)
            with self.lock:
                before = {e.charger:e.id for e in self.station.vehicles if e.charger and e.power_kw > 0}
                accepted = command.get('run_id') == self.run_id and self.station.accept(command)
                if accepted:
                    after = {e.charger:e.id for e in self.station.vehicles if e.charger and e.power_kw > 0}
                    for charger in self.station.chargers:
                        if before.get(charger) != after.get(charger):
                            now = self.station.hour
                            if charger in self.last_switch and now-self.last_switch[charger] < .1-1e-8:
                                self.rapid_switch_count += 1
                            self.last_switch[charger] = now
                            self.switch_count += 1
            client.publish('ev/ack',json.dumps({'run_id':self.run_id,'sequence':command.get('sequence'),
                'accepted':accepted, 'received_at':time.time(),
                'response_ms':max(0,(time.time()-command['sensor_timestamp'])*1000),
                'inference_ms':command.get('inference_ms'),
                'decision_ms':command.get('decision_ms'),
                'switch_count':self.switch_count,'rapid_switch_count':self.rapid_switch_count}),qos=1)
        except (ValueError, KeyError, TypeError) as exc:
            print('Rejected actuator message:',exc,flush=True)


if __name__ == '__main__':
    raise SystemExit('Actuator is attached to the sensor/plant process. Run python simulator.py.')
