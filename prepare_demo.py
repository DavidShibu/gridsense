"""Train compatible demo models locally using synthetic history staged in SQLite.

This is offline installation-time preparation, not live sensor ingestion. The
running application still uses MQTT -> Node-RED -> SQLite -> decision -> MQTT.
"""
import json
import shutil
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from sender.station_core import historical_sessions
from station_store import ingest
from ml_train import train


def prepare(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    bins = [[0.0]*24 for _ in range(42)]
    for row in historical_sessions(days=42):
        bins[row['day']][row['hour']] += row['energy_kwh']
    payload = {'kind': 'history', 'dataset': 'synthetic-history-v5',
               'source': 'installation_time_synthetic_history',
               'samples': [{'day': day, 'hour': hour, 'energy_kwh': value}
                           for day, values in enumerate(bins) for hour, value in enumerate(values)]}
    print('Preparing five models for this Python environment; please wait...', flush=True)
    with tempfile.TemporaryDirectory(prefix='gridsense-setup-') as tmp:
        temporary = Path(tmp)
        db = temporary/'training.db'
        ingest(payload, db)
        report = train(db, temporary/'models')
        target = root/'artifacts'
        target.mkdir(parents=True, exist_ok=True)
        pending = target/'bundle.tmp'
        shutil.copyfile(temporary/'models/bundle.pkl', pending)
        pending.replace(target/'bundle.pkl')
    metadata = {'python': sys.version.split()[0],
                'packages': {p: version(p) for p in ('numpy', 'scikit-learn', 'scipy', 'xgboost')},
                'selected_model': report['selected_model'], 'training_rows': 1008,
                'preparation': 'offline installation-time synthetic history staged in temporary SQLite'}
    (target/'runtime.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print('Local models ready. Selected: '+report['selected_model'], flush=True)
    return metadata


if __name__ == '__main__':
    prepare()
