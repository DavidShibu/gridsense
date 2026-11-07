param([switch]$SyntheticOnly)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Get-Command python -ErrorAction Stop | Out-Null
Get-Command node -ErrorAction Stop | Out-Null
Get-Command npm.cmd -ErrorAction Stop | Out-Null
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
& '.\.venv\Scripts\python.exe' -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else "Python 3.10 or newer is required")'
if ($LASTEXITCODE -ne 0) { throw 'The existing .venv needs Python 3.10 or newer.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-station.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed. See the Python compatibility instructions in README.md.' }
& npm.cmd ci --prefix node-red --omit=dev --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Node-RED dependency installation failed.' }
if ($SyntheticOnly) {
    & '.\.venv\Scripts\python.exe' prepare_demo.py --synthetic-only
} else {
    & '.\.venv\Scripts\python.exe' prepare_demo.py
}
if ($LASTEXITCODE -ne 0) { throw 'Local model preparation failed. Check the error above.' }
Write-Host 'Setup complete. Run ./start_demo.ps1.'
