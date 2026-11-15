@echo off
rem Starts the local API (127.0.0.1:8765) and the frontend dev server (127.0.0.1:5173), then opens the browser.
rem Requires setup_windows.ps1 to have been run once.
setlocal
set "PY=%LOCALAPPDATA%\NoiseBox\venv310\Scripts\python.exe"
if not exist "%PY%" (
  echo Python 3.10 environment not found. Run setup_windows.ps1 first.
  exit /b 1
)
cd /d "%~dp0"
start "noise-box API" /D "%~dp0backend" "%PY%" run_server.py
start "noise-box UI" /D "%~dp0frontend" cmd /c "npm run dev"
timeout /t 6 /nobreak >nul
start "" http://127.0.0.1:5173/
echo MATLAB takes about 15 seconds to start; the status pill turns green when ready.
endlocal
