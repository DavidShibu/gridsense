"""Build a complete submission from an explicit allowlist, with SHA-256 checksums."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
FILES = [
    'README.md', 'changes.md', 'GridSense_Final_Report.md', 'GridSense_Presentation.pptx',
    'refererncesss.png', 'pyproject.toml', 'requirements-station.txt',
    'requirements-tested.txt', 'package_submission.py',
    'simulator.py', 'actuator.py', 'station_core.py', 'station_simulator.py',
    'station_store.py', 'station_service.py', 'decision_engine.py',
    'ml_train.py', 'tariff.py', 'tou_scheduler.py',
    'evaluate_control.py', 'evaluate_tou.py', 'verify_diagnoses.py',
    'start.ps1', 'start_station.ps1', 'start.sh',
    'node-red/flows.json', 'node-red/settings.js', 'node-red/package.json',
    'node-red/package-lock.json', 'node-red/demo-broker.cjs',
    'node-red/build-presentation.cjs', 'node-red/validate-upgrades.cjs',
]


def build():
    files = set(FILES)
    for pattern in ('tests/*.py', 'node-red/templates/*.vue', 'artifacts/*.json', 'artifacts/*.pkl'):
        files.update(p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern))
    missing = [name for name in sorted(files) if not (ROOT/name).is_file()]
    if missing:
        raise FileNotFoundError('Missing submission files: ' + ', '.join(missing))
    manifest = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(files)}
    output = ROOT/'submission'/'GridSense_Team3.zip'
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix('.zip.tmp')
    with ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT/name, 'GridSense/'+name)
        archive.writestr('GridSense/SUBMISSION_MANIFEST.json', json.dumps(manifest, indent=2))
    with ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP integrity check failed')
        for name, digest in manifest.items():
            if hashlib.sha256(archive.read('GridSense/'+name)).hexdigest() != digest:
                raise RuntimeError('Checksum mismatch: ' + name)
    temporary.replace(output)
    print(output)
    print(f'{len(files)} files plus manifest; {output.stat().st_size:,} bytes; integrity verified.')


if __name__ == '__main__':
    build()
