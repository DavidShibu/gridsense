"""SQLite boundary: ingest commits before any analytics reads."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB = Path(__file__).with_name('station.db')


@contextmanager
def database(path=DB):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS demand_samples (dataset TEXT, day INTEGER, hour INTEGER, energy_kwh REAL, source TEXT, PRIMARY KEY(dataset,day,hour))')
        conn.execute('CREATE TABLE IF NOT EXISTS cycles (run_id TEXT, sequence INTEGER, hour REAL, telemetry TEXT, decision TEXT, PRIMARY KEY(run_id,sequence))')
        conn.execute('CREATE TABLE IF NOT EXISTS actuator_acks (run_id TEXT, sequence INTEGER, payload TEXT, PRIMARY KEY(run_id,sequence))')
        conn.execute('CREATE TABLE IF NOT EXISTS ml_evaluations (created_at REAL PRIMARY KEY, report TEXT)')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ingest(payload, path=DB):
    with database(path) as conn:
        if payload.get('kind') == 'history':
            rows = payload['samples']
            if len(rows) > 5000:
                raise ValueError('Too many history samples')
            import math
            for r in rows:
                if not (0 <= r['hour'] < 24 and r['day'] >= 0 and math.isfinite(r['energy_kwh']) and r['energy_kwh'] >= 0):
                    raise ValueError('Invalid history sample')
            # Each history message is a complete dataset snapshot. Replace it
            # atomically so a shorter real window cannot leave stale old days.
            conn.execute('DELETE FROM demand_samples WHERE dataset=?', (payload['dataset'],))
            # Refresh rowid order so /health describes the latest replay.
            conn.executemany('INSERT OR REPLACE INTO demand_samples VALUES (?,?,?,?,?)',
                             [(payload['dataset'], r['day'], r['hour'], r['energy_kwh'], payload['source']) for r in rows])
            if payload['source'] == 'synthetic-fallback':
                print('[FALLBACK] Using synthetic history (received and stored)', flush=True)
            return {'stored_history_rows': len(rows)}
        conn.execute('INSERT OR IGNORE INTO cycles VALUES (?,?,?,?,NULL)',
                     (payload['run_id'], payload['sequence'], payload['hour'], json.dumps(payload, allow_nan=False)))
    return {'run_id': payload['run_id'], 'sequence': payload['sequence']}


def read_state(key, path=DB):
    with database(path) as conn:
        row = conn.execute('SELECT telemetry FROM cycles WHERE run_id=? AND sequence=?',
                           (key['run_id'], key['sequence'])).fetchone()
        if not row:
            raise ValueError('Telemetry not committed to SQLite')
        return json.loads(row['telemetry'])
