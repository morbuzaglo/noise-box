# One-time setup (Windows). Keeps the venv and node_modules OUTSIDE OneDrive.
# Requires: MATLAB with the Engine API for Python (R2023a supports Python 3.8-3.10), Python 3.10, Node.js.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$base = Join-Path $env:LOCALAPPDATA "NoiseBox"
$venv = Join-Path $base "venv310"
$matlab = $env:NOISEBOX_MATLAB_ROOT
if (-not $matlab) { $matlab = "C:\Program Files\MATLAB\R2023a" }

if (-not (Test-Path (Join-Path $matlab "bin\matlab.exe"))) { throw "MATLAB not found at $matlab. Set NOISEBOX_MATLAB_ROOT." }
New-Item -ItemType Directory -Force $base | Out-Null
if (-not (Test-Path $venv)) { py -3.10 -m venv $venv }
$py = Join-Path $venv "Scripts\python.exe"

& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $root "backend\requirements.txt")

# The Engine must be built from its own folder (pip install of the folder fails with "installation is corrupted").
$build = Join-Path $base "engbuild"
Push-Location (Join-Path $matlab "extern\engines\python")
& $py setup.py build --build-base=$build install
Pop-Location
& $py -c "import matlab.engine; print('MATLAB Engine import OK')"

# node_modules lives outside OneDrive; the directory must be named node_modules for module resolution.
$nm = Join-Path $base "fe\node_modules"
New-Item -ItemType Directory -Force (Split-Path $nm) | Out-Null
New-Item -ItemType Directory -Force $nm | Out-Null
$link = Join-Path $root "frontend\node_modules"
if (-not (Test-Path $link)) { New-Item -ItemType Junction -Path $link -Target $nm | Out-Null }
Push-Location (Join-Path $root "frontend")
npm install --no-audit --no-fund
Pop-Location
Write-Host "Setup complete. Run start.bat"
