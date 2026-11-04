"""Create a source-only submission ZIP; no credentials, caches or databases."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
files = ['station_core.py', 'station_service.py', 'station_simulator.py',
         'simulator.py', 'actuator.py', 'ml_train.py', 'station_store.py',
         'decision_engine.py', 'evaluate_control.py', 'update_flow.py',
         'AUDIT_RUBRIC.md', 'REPORT_V5.md', 'tests/test_rubric.py',
         'FIXES_REVIEW.md', 'tests/test_fixes.py', 'verify_diagnoses.py',
         'start.ps1', 'start_station.ps1', 'start.sh', 'requirements-station.txt',
         'README.md', 'REPORT_V4.md', 'GridSense_Presentation.pptx',
         'package_submission.py', 'tests/test_station.py', 'tests/live_check.py',
         'node-red/flows.json', 'node-red/settings.js', 'node-red/package.json',
         'node-red/package-lock.json', 'node-red/demo-broker.cjs',
         'node-red/build-presentation.cjs']
files += [str(p.relative_to(root)) for p in sorted((root/'artifacts').glob('*')) if p.suffix in ('.json','.pkl')]
output = root/'submission'
output.mkdir(exist_ok=True)
with ZipFile(output/'GridSense_Team3.zip', 'w', ZIP_DEFLATED) as archive:
    for name in files:
        archive.write(root/name, 'GridSense/'+name)
print(output/'GridSense_Team3.zip')
