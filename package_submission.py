"""Build the demo-only ZIP from an explicit runtime allowlist."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
FILES = [
    'setup_demo.ps1', 'start_demo.ps1',
    'requirements-station.txt', 'prepare_demo.py',
    'mqtt-public.json',
    'sender/simulator.py', 'sender/actuator.py', 'sender/station_core.py',
    'sender/tariff.py', 'sender/mqtt-public.json',
    'station_store.py', 'station_service.py', 'decision_engine.py',
    'ml_train.py', 'tou_scheduler.py',
    'node-red/flows.json', 'node-red/settings.js', 'node-red/build-public-flow.cjs',
]


def build():
    paths = {name: ROOT/name for name in FILES}
    paths['README.md'] = ROOT/'DEMO_README.md'
    missing = [str(p) for p in paths.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError('Required runtime files missing: ' + ', '.join(missing))
    if json.loads((ROOT/'mqtt-public.json').read_text()) != json.loads((ROOT/'sender/mqtt-public.json').read_text()):
        raise ValueError('Project and sender MQTT profiles must match')
    # Keep presentation tooling and local-broker dev dependencies out of the demo.
    staging = ROOT/'submission'/'runtime-node'
    staging.mkdir(parents=True, exist_ok=True)
    package = json.loads((ROOT/'node-red/package.json').read_text())
    package.pop('devDependencies', None)
    package['scripts'] = {'start': 'node-red --userDir . --settings settings.js flows.public.json'}
    (staging/'package.json').write_text(json.dumps(package, indent=2))
    (staging/'package-lock.json').write_bytes((ROOT/'node-red/package-lock.json').read_bytes())
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    if not npm:
        raise RuntimeError('npm is required to prepare the runtime dependency lock')
    subprocess.run([npm, 'install', '--package-lock-only', '--ignore-scripts', '--offline',
                    '--no-audit', '--no-fund', '--prefix', str(staging)], check=True)
    for name in ('package.json', 'package-lock.json'):
        paths['node-red/'+name] = staging/name
    content = {name: path.read_bytes() for name, path in paths.items()}
    output = ROOT/'submission'/'GridSense_Team3.zip'
    temporary = output.with_suffix('.zip.tmp')
    with ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            archive.writestr('GridSense/'+name, data)
    with ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP integrity check failed')
        for name, data in content.items():
            if hashlib.sha256(archive.read('GridSense/'+name)).digest() != hashlib.sha256(data).digest():
                raise RuntimeError('Checksum mismatch: '+name)
    temporary.replace(output)
    print(output)
    print(f'{len(content)} runtime/demo files; {output.stat().st_size:,} bytes; integrity verified.')


if __name__ == '__main__':
    build()
