"""Local HTTP analytics/persistence service. Node-RED owns MQTT integration."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from station_core import demand_model, schedule

DB = Path(__file__).with_name("station.db")
MODEL = demand_model()


def process(state, path=DB):
    decision = schedule(state, MODEL)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS cycles (run_id TEXT, sequence INTEGER, hour REAL, telemetry TEXT, decision TEXT, PRIMARY KEY(run_id, sequence))")
        conn.execute("INSERT OR REPLACE INTO cycles VALUES (?,?,?,?,?)",
                     (state["run_id"], state["sequence"], state["hour"],
                      json.dumps(state, allow_nan=False), json.dumps(decision, allow_nan=False)))
    return {"state": state, "decision": decision}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.respond({"status": "ok"})

    def respond(self, data):
        body = json.dumps(data, allow_nan=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/cycle":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 1000000:
                raise ValueError("Invalid request size")
            state = json.loads(self.rfile.read(size))
            self.respond(process(state))
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            self.send_error(400, str(exc))


if __name__ == "__main__":
    print("GridSense analytics: http://127.0.0.1:8765", flush=True)
    HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
