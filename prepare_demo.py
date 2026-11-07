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

from sender.simulator import history_payload
from station_store import ingest
from ml_train import train


def prepare(root=None, synthetic_only=False):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    payload = history_payload(synthetic_only=synthetic_only)
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
        shutil.copyfile(temporary/'models/ml_comparison.json', target/'ml_comparison.json')
    metadata = {'python': sys.version.split()[0],
                'packages': {p: version(p) for p in ('numpy', 'scikit-learn', 'scipy', 'xgboost')},
                'selected_model': report['selected_model'], 'training_rows': len(payload['samples']),
                'data_source':report['data_source'],
                'preparation': 'installation-time history staged in temporary SQLite (live ingestion uses MQTT)'}
    (target/'runtime.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print('Local models ready. Selected: '+report['selected_model'], flush=True)
    return metadata


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--synthetic-only', action='store_true')
    prepare(synthetic_only=parser.parse_args().synthetic_only)
