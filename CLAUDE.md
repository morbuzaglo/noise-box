# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Working end to end on Windows with real MATLAB R2023a: flat point, 2D section, 3D DEM with walls/buildings/ground areas/fabric screens/enclosure, audio pipeline, projects + Excel export, Test Lab, diagnostics. 193 pytest tests pass; the in-app Test Lab shows PASS 51, FAIL 0, BLOCKED 4 (ISO/TR T10, T14, T18, T19), SKIP 1, EXTERNAL 6. Read `docs/VALIDATION_REPORT.md` before claiming anything about conformance: tests are self-authored plus ISO/TR 17534-3 and ISO 9613-1 data, ISO 9613-2:2024 itself has no independent benchmark, and several model decisions were calibrated against the TR reference (listed there).

Not implemented: reflections (7.5), A_misc, multi-source, FAST geometry mode, concave-footprint lateral paths, Hebrew/RTL. Opening a stored case (Projects -> Open in view, or Test Lab -> Load as case) restores it into the Section/Terrain/Point view, runs it and allows Save changes and rerun; this was checked in a browser for terrain cases. Still only type-checked, not clicked: audio page, fabric/enclosure panels, PNG export, watch mode.

## Goal

A local acoustic propagation simulator (ISO 9613-2): React/TypeScript frontend, Python FastAPI backend, and MATLAB `.m` files as the ONLY acoustic solver. The backend must never reimplement the physics. Edits to `.m` files must take effect on the next run without restarting the app (file hashing, dependency-aware cache invalidation, `clear functions`, path refresh). Cache keys must include physical inputs plus `.m` dependency hashes.

## Reference documents (in this folder)

(Full detail and findings per file: `docs/VALIDATION_REPORT.md`. `ISO 9613-1 1993.pdf` has an unrelated ISO 5077 document appended at the end.)

- `ISO 9613-1 1993.pdf`, `standard_iso_9613-2_1996.pdf`, `standard_iso_9613-2_2024.pdf`: image-only scans, no text layer. Read by rendering page images; cite page and formula for every golden test value.
- `ISO 9613-2 2024 DAmd 1.PNG`: screenshot with only the replacement eq. (18) `Dz = 10 lg[3 + (C2/lambda) C3 z Kmet]` for z > zmin (else 0) and eq. (21) `Kmet = exp[-(1/2000) sqrt(dss dsr d / (2 z))]` for z > 0 (else 1). Nothing else of the draft is available, so draft mode is limited to these two equations.
- `ISO_TR 17534-1_2015.pdf` is actually the full standard ISO 17534-1; `-2` is the TR with general QA recommendations; `-3` is the TR with the ISO 9613-2 benchmarks T01-T19. All three have text layers (`pdftotext` is available). T01-T19 target the 1996 edition, so comparing them needs a separate 1996 compatibility mode.

Keep three formula modes strictly separate: 2024 published, 2024 + DAmd 1 (labelled DRAFT), and 1996 compatibility.

## Commands

MATLAB R2023a (Update 5) is the target. The default Python 3.12 is NOT supported by the Engine API; use the 3.10 venv.

```
# Run everything (API 127.0.0.1:8765 + Vite 127.0.0.1:5173 + browser). setup_windows.ps1 is UNTESTED as a script; its steps were run by hand.
start.bat

# Tests (real MATLAB; ~15 s engine start per session; hot-reload tests start one engine each (~80 s); full suite ~6 min, 190 tests)
%LOCALAPPDATA%\NoiseBox\venv310\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
%LOCALAPPDATA%\NoiseBox\venv310\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --deselect tests/test_hot_reload.py   # skip the slow ones
%LOCALAPPDATA%\NoiseBox\venv310\Scripts\python.exe -m pytest tests/test_core_analytic.py::test_dz_2024_single_edge_1khz -q   # single test
# Benchmarks / Test Lab without the UI: in MATLAB, addpath('matlab/core'); r = nb_testlab('run','G3-T08');  r = nb_bench_run('T08');
# Demo data: python tools/make_samples.py   (synthetic files in samples/)
# pytest must stay <9: pytest 9.2 crashes on this Python 3.10.0 (NodeId _str_cache error)

# Frontend (from frontend/): npm run build   (tsc --noEmit + vite build). node_modules is a junction to %LOCALAPPDATA%\NoiseBox\fe\node_modules
# (the target dir must be literally named node_modules, and npm install can replace the junction with a real dir: re-check after installs)

# Engine venv (already created): %LOCALAPPDATA%\NoiseBox\venv310
# Install the Engine (plain `pip install` of the extern folder fails with "installation of MATLAB is corrupted"):
cd "C:\Program Files\MATLAB\R2023a\extern\engines\python"
%LOCALAPPDATA%\NoiseBox\venv310\Scripts\python.exe setup.py build --build-base=<tmp dir> install

# Run MATLAB code headless (output is buried in Java stack noise: redirect to a file and grep your own lines)
"C:\Program Files\MATLAB\R2023a\bin\matlab.exe" -batch "addpath('matlab/core'); ..." > out.txt 2>&1
```

Engine start takes about 14 s, so keep one managed worker alive rather than starting per call. The solver must stay **toolbox-free** (base MATLAB only): octave filters come from `nb_butter_sos.m`, not `butter`/`zp2sos`/Audio Toolbox, and `tests/test_audio.py::test_solver_library_needs_no_toolbox` fails if any `.m` file in `matlab/core` needs a toolbox. Do not call toolbox functions (check with `matlab.codetools.requiredFilesAndProducts`).

## Architecture

- `matlab/core/*.m`: the only solver. One function per ISO term (`nb_*`), all returning 1x8 band vectors. `run_acoustic_case.m` is the stable entry point (struct in, scalar struct out: the Engine cannot return struct arrays). Formula/page citations are in each file header.
- `backend/app/matlab_worker.py`: one thread owns the single Engine. Before every job it hashes the `.m` files; on change it runs `clear functions`, re-adds the path and drops the cache. Cache key = inputs + SHA-256 of every `.m` file reachable from the entry (identifier scan, comments stripped). Only functions in the library folder may be called; there is no eval endpoint.
- `backend/app/main.py`: FastAPI, pydantic validation (8 bands, G in [0,1], RH, pressure) and the endpoints `/api/run`, `field2d`, `field3d`, `case3d`, DEM and audio upload, diagnostics. Routers are included at the bottom: `projects_api.py` (projects, cases, compare, Excel/CSV export via `export_xlsx.py`) and `testlab_api.py`. Library path overridable with `NOISEBOX_MATLAB_LIB`. `matlab_worker.run()` is the cached struct-in/struct-out call; `run_call()` is for positional args (Test Lab, diagnostics).
- `frontend/src`: React + TypeScript + Vite + Plotly. `App.tsx` switches between views (point, `SectionView`, `TerrainView`, `AudioView`, `ProjectsView`, `TestLabView`, `DiagnosticsView`); `api.ts` holds every request type. Plotly bars need a category x axis (a numeric axis spreads octave bands wrongly). `A_WEIGHT` in `api.ts` must match `nb_bands.m`. UI shell: `App.tsx` owns the rail, panels, theme, undo/redo (snapshot of the shared parameters), presets and shortcuts; `Palette.tsx` builds the parameter search from the live `.field`/`.band` labels in the left panel (so new parameters appear automatically, keep them inside `Sec`/`.field`/`.band`); `ui.tsx` has toasts and `confirmDialog`/`promptDialog` (do not use `window.confirm`/`prompt`); styles are tokens in `styles.css`, and Plotly reads `--ink`, `--line`, `--accent`, `--bad` from it, so keep those names. Redesign work must not change request-building code or `api.ts`.
- MATLAB Engine return-value rules that shaped the code: only scalar structs can be returned (no struct arrays: use cell arrays of scalar structs or parallel vectors); 1x1 logicals come back as Python `bool`; NaN is sent to the browser as `null` (`_json_safe`), never as a number; use `skipFingerprint` for per-point calls inside grid loops.
- Model decisions calibrated against ISO/TR 17534-3 (see `docs/FORMULA_MATRIX.md`, "iso1996 compatibility mode" and "Lateral construction"): lateral cross-section clipped at roof height, non-blocking obstacles added to the string, 63 Hz lambda = 340/62.5 and no factor-8 rule in `iso1996` only. Changing `nb_lateral`/`nb_dz` can break T08-T17: rerun `nb_testlab` group G3.
- `matlab/core/nb_testlab.m` is the Test Lab registry (G1-G6; each test lists the production functions it calls and a documentary source). `nb_bench_cases.m` holds the ISO/TR 17534-3 inputs and reference values with table/page citations; `nb_bench_run.m` solves them in `iso1996` mode.
- `backend/app/store.py` resolves the data dir on every call (`NOISEBOX_DATA`); `tests/conftest.py` sets one per session. `projects_api.py` runs stored cases through the same endpoints and stores the result with the code fingerprint.
- 3D pipeline: `nb_receiver_3d` (profile = DEM + obstacle tops, exact hull top path, lateral paths via `nb_lateral`, ground areas, screens) is shared by `run_case_3d` and `run_field_3d`.
- Modes: `iso2024` published eqs. (18)-(21). Mode `draft2026` swaps only eqs. (18) and (21) per the DAmd 1 screenshot. Published (21) uses max/min of dss,dsr and (z - zmin); the draft uses sqrt(dss dsr d/(2z)) and K_met = 1 for z <= 0.

## Conventions

- Do not create a `.venv` inside the project (OneDrive-synced); keep environments and temp files in `%LOCALAPPDATA%\NoiseBox`.
- Python on this machine defaults to cp1255; pass `encoding='utf-8'` to `open()`.
- All octave-band quantities are 1x8 vectors over 63...8000 Hz. Combine bands into broadband values only at the end, by energy sum, never by averaging dB. Do not clamp negative `A_gr`. Never apply `C_met` by default.
- Test expected values must come from the standards or an independent calculation, never from the production function under test. Tests that touch project storage must not set `NOISEBOX_DATA` themselves (`conftest.py` does it once per session; module-level overrides made files land in the wrong folder).
- Write long scripts with the Write tool and run them from a file: large bash heredocs mixing quote styles were rejected at parse time.
- `README.md` has setup and layout; `docs/FORMULA_MATRIX.md` has every equation with its page; `docs/VALIDATION_REPORT.md` has results, blocked cases and limitations. Update the last two when behaviour or test counts change.
- Do not read or copy third-party dBmap/noisetools code if a copy exists next to this project (it is marked private comparison only). The MATLAB core here is written from scratch.
- The standards (`*.pdf`, the DAmd screenshot) are copyrighted and are git-ignored: supply your own copies in the project folder. `samples/` is generated by `tools/make_samples.py` and also ignored.
