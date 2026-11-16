# Noise Box

A local outdoor sound-propagation simulator (ISO 9613-2). A React/TypeScript browser UI talks to a local FastAPI backend, which drives **MATLAB** through the MATLAB Engine API. **All acoustic calculation is in MATLAB `.m` files**; Python and JavaScript only handle orchestration, GIS/audio I/O, persistence, reports and display. Nothing needs the cloud.

> Status: working end to end on Windows with MATLAB R2023a. See `docs/VALIDATION_REPORT.md` for what was actually verified, what is blocked and what is approximate. **No ISO certification or conformance of ISO 9613-2:2024 is claimed.**

## Standards are not included

The ISO standards and the DAmd 1 screenshot are copyrighted and are **not** in this repository (`.gitignore` excludes them). To reproduce the benchmark and golden-value work you need your own licensed copies of ISO 9613-1:1993, ISO 9613-2:1996 and :2024, ISO/TR 17534-3:2015 (the T01-T19 data is transcribed into `matlab/core/nb_bench_cases.m` with table and page citations) and, for the draft mode, the DAmd 1 pages. The application and its tests run without the PDFs.

## What it does

- Single point source, eight octave bands (63-8000 Hz) carried through every stage; broadband values by energy sum only.
- Source strength as **sound power level L_W (dB re 1 pW)**, manual or A-weighted input, or estimated from a calibrated recording.
- Scenes: flat ground, a 2D X-Z terrain profile, or a 3D DEM (ESRI ASCII, XYZ/CSV, GeoTIFF with CRS check) with walls, buildings, ground-factor areas, transmissive fabric screens and a source enclosure.
- Top and lateral diffraction (ISO 9613-2:2024 7.4), ground, atmosphere, `C_met` only on request.
- Per-band limits: a point is PASS only if **every** limited band passes; maps, per-point inspector, margins.
- Projects and cases (SQLite + directories): **open a stored case in its editor view** (3D terrain, 2D section or flat point), edit it, run it, click points, save changes; duplicate-and-change, comparison, **one Excel workbook with one sheet per case**, CSV, PNG map export.
- **Test Lab**: 62 registered tests, ISO/TR 17534-3 T01-T19 (15 run, 4 blocked), reports and a JSON log.
- MATLAB **hot reload**: edit a `.m` file, the next run uses it; caches are keyed on the code hashes.
- **Workbench UI**: view rail (Alt+1..7), collapsible sections, resizable and collapsible side panels (Ctrl+B, Ctrl+Shift+B), light/dark theme, status bar, edited-parameter markers with per-field reset, undo/redo of the shared parameters (Ctrl+Z / Ctrl+Shift+Z outside text fields), parameter presets (saved in the browser), command palette that searches every parameter, view and action (Ctrl+K), in-app confirm dialogs and toasts, CSV export of the point result. These are presentation only: the values sent to the solver are unchanged.

Three calculation modes are never mixed: `iso2024` (published), `draft2026` (DRAFT DAmd 1 eqs. 18/21, experimental) and `iso1996` (compatibility for the ISO/TR benchmarks). See `docs/FORMULA_MATRIX.md`.

## Requirements

| Need | Notes |
|---|---|
| MATLAB with the Engine API for Python | the full MATLAB install (Runtime alone is not enough). R2023a supports Python 3.8-3.10. **No MATLAB toolbox is required**: the solver uses base MATLAB only (the octave filters are designed by `nb_butter_sos.m`; `tests/test_audio.py` asserts via `requiredFilesAndProducts` that no `.m` file needs a toolbox) |
| Python 3.10 | the default Python 3.12 is not supported by R2021a/R2023a Engines |
| Node.js 18+ | frontend build and dev server |

Windows is the tested platform.

## Setup (Windows)

```powershell
.\setup_windows.ps1        # venv in %LOCALAPPDATA%\NoiseBox, Engine install, node_modules junction, npm install
start.bat                  # API on 127.0.0.1:8765, UI on 127.0.0.1:5173, opens the browser
```

Notes learned the hard way:
- Do **not** `pip install` the Engine folder directly (it reports "installation of MATLAB is corrupted"). The script runs `python setup.py build --build-base=<tmp> install` from the Engine folder.
- Keep the virtualenv and `node_modules` outside OneDrive. The script makes `frontend\node_modules` a junction to `%LOCALAPPDATA%\NoiseBox\fe\node_modules` (the target directory must be named `node_modules`).
- pytest must be `< 9` on Python 3.10.0.
- `setup_windows.ps1` was assembled from steps run by hand and has not been executed as one script. `setup.sh` and `start.sh` (macOS/Linux) are untested.

The MATLAB library folder is `matlab/core`; override it with `NOISEBOX_MATLAB_LIB`. Project data lives in `%LOCALAPPDATA%\NoiseBox\projects` (override `NOISEBOX_DATA`).

## Layout

```
matlab/core/        the numerical solver (nb_* functions, run_* entry points, Test Lab registry)
backend/app/        FastAPI: matlab_worker (single Engine thread, hot reload), main (API), dem, audio,
                    store (SQLite + project dirs), projects_api, export_xlsx, testlab_api
frontend/src/       React views: point, 2D section, 3D terrain, audio, projects, Test Lab, diagnostics
tests/              pytest suite (real MATLAB), 193 tests
tools/make_samples.py  synthetic demo data -> samples/
docs/               FORMULA_MATRIX.md, VALIDATION_REPORT.md
```

Entry points called by the API: `run_acoustic_case`, `run_case_2d`, `run_field_2d`, `run_case_3d`, `run_field_3d`, `run_audio_analysis`, `nb_testlab`, `nb_diagnostics`. Only functions inside the library folder can be called; there is no eval endpoint, uploads get random server-side names, and the server binds to 127.0.0.1.

## Units and conventions

Metres; elevations absolute unless a name says "above ground"; heights of source/receiver are above **local** ground; sound power in dB re 1 pW; sound pressure in dB re 20 uPa; `A_gr` may be negative and is never clamped; broadband = energy sum of the eight modelled bands (not the full audio spectrum). Georeferenced rasters in degrees are reprojected to UTM; files without CRS must be declared metric.

## Hot reload

Every job re-hashes the `.m` files of the library. If any changed, MATLAB's function cache is cleared, the path re-added, and the result cache dropped. Cache keys contain the inputs and the SHA-256 of every `.m` file the entry point reaches, so an old result is never reused. Each stored result keeps the code fingerprint that produced it. Use "MATLAB diagnostics" for the function table, the Refresh button and watch mode. `tests/test_hot_reload.py` edits a copy of the library in a running session and checks the output changes by exactly the edit.

## Tests

```powershell
%LOCALAPPDATA%\NoiseBox\venv310\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Starts real MATLAB (about 15 s per Engine; the hot-reload tests start several). Full run about 6 minutes. In the app, open **Test Lab** and press "Run all tests".

## Demo data

`python tools/make_samples.py` writes **synthetic** data to `samples/`: a calibrator recording and a machine recording (about 80 dB with that calibrator), a background recording, ridge and hill DEMs (ESRI ASCII), a 2D profile CSV, a wall with a light fabric, receivers and a source preset. Nothing in it is measured or surveyed. The default source spectrum in the UI is likewise a synthetic example.

## Known limitations

See the end of `docs/VALIDATION_REPORT.md`: no reflections or `A_misc`, single source, hull-based lateral paths (no concave courtyards), custom octave filters, engineering approximations for fabrics and enclosures, untested UI paths, no Hebrew/RTL yet.
