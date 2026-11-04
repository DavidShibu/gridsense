"""Node-RED HTTP persistence/evaluation boundary. Never publishes MQTT itself."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from station_store import DB, database, ingest
from decision_engine import decide, initialize_models


def closed_loop(run_id,path=DB):
    with database(path) as conn:
        states = [json.loads(r['telemetry']) for r in conn.execute('SELECT telemetry FROM cycles WHERE run_id=? ORDER BY sequence',(run_id,))]
        acks = [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM actuator_acks WHERE run_id=?',(run_id,))]
    if not states:
        return {}
    last = states[-1]
    departed = [e for e in last['vehicles'] if e['status']=='departed']
    required = sum(e['delivered_kwh']+e['remaining_kwh'] for e in departed)
    latencies = sorted(a['response_ms'] for a in acks if a['accepted'])
    inference = [a['inference_ms'] for a in acks if a['accepted'] and a.get('inference_ms') is not None]
    decisions = [a['decision_ms'] for a in acks if a['accepted'] and a.get('decision_ms') is not None]
    return {'departed_vehicles':len(departed),
            'deadline_success_fraction':sum(e['remaining_kwh'] <= .01 for e in departed)/len(departed) if departed else None,
            'departed_energy_fulfillment_fraction':sum(e['delivered_kwh'] for e in departed)/required if required else None,
            'unmet_departure_kwh':sum(e['remaining_kwh'] for e in departed),
            'peak_site_kw':max(s['load_kw'] for s in states),
            'capacity_violation_samples':sum(s['load_kw'] > s['capacity_kw']+1e-6 for s in states),
            'operating_limit_kw':last['capacity_kw']*.95,
            'safety_margin_violation_samples':sum(s['load_kw'] > s['capacity_kw']*.95+1e-6 for s in states),
            'accepted_commands':len(latencies),'acknowledgements':len(acks),
            'response_mean_ms':sum(latencies)/len(latencies) if latencies else None,
            'response_p95_ms':latencies[min(len(latencies)-1,int(.95*len(latencies)))] if latencies else None,
            'mean_inference_ms':sum(inference)/len(inference) if inference else None,
            'mean_decision_ms':sum(decisions)/len(decisions) if decisions else None,
            'socket_switches':max((a.get('switch_count',0) for a in acks),default=0),
            'rapid_switches':max((a.get('rapid_switch_count',0) for a in acks),default=0)}


def process(payload,path=DB):
    key = ingest(payload,path)  # Separate committed transaction BEFORE decision/model input reads.
    if 'stored_history_rows' in key:
        return key
    result = decide(key,path)
    result['closed_loop'] = closed_loop(key['run_id'],path)
    return result


class Handler(BaseHTTPRequestHandler):
    def respond(self,data):
        body = json.dumps(data,allow_nan=False).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != '/health':
            self.send_error(404)
            return
        with database() as conn:
            count = conn.execute('SELECT count(*) FROM demand_samples').fetchone()[0]
        self.respond({'status':'ok','history_rows':count})

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length',0))
            if not 0 < size <= 1000000:
                raise ValueError('Invalid request size')
            payload = json.loads(self.rfile.read(size))
            if self.path == '/store':
                self.respond(ingest(payload))
            elif self.path == '/decide':
                result = decide(payload)
                result['closed_loop'] = closed_loop(payload['run_id'])
                self.respond(result)
            elif self.path == '/cycle':
                self.respond(process(payload))
            elif self.path == '/ack':
                with database() as conn:
                    # Keep successful application evidence if QoS redelivery later gets rejected.
                    conn.execute('INSERT INTO actuator_acks VALUES (?,?,?) ON CONFLICT(run_id,sequence) DO UPDATE SET payload=excluded.payload WHERE json_extract(actuator_acks.payload,\'$.accepted\')=0',
                                 (payload['run_id'],payload['sequence'],json.dumps(payload)))
                self.respond({'stored':True})
            else:
                self.send_error(404)
        except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
            self.send_error(400,str(exc))


if __name__ == '__main__':
    initialize_models()
    print('GridSense SQLite/decision service: http://127.0.0.1:8765',flush=True)
    HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
