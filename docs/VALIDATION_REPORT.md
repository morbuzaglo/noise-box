# Validation report

Software: noise-box 0.1. MATLAB R2023a Update 5. **No MATLAB toolbox is required**: `matlab.codetools.requiredFilesAndProducts` over every file of `matlab/core` returns base MATLAB only (asserted by a test). Python 3.10.0 (Engine API). All acoustic calculation executes in MATLAB `.m` files; every test below that names a function calls that function through the real MATLAB Engine.

**Passing these tests is not an ISO certification and does not show conformance of ISO 9613-2:2024.** The tests are self-authored, plus the benchmark data of ISO/TR 17534-3 and the tables of ISO 9613-1.

## Summary of the last full run

| Suite | Result |
|---|---|
| `python -m pytest tests` (MATLAB-backed) | **193 passed**, 0 failed (about 6 minutes) |
| Test Lab in the application (`Run all tests`) | 62 tests: **PASS 51, FAIL 0, BLOCKED 4, SKIP 1, EXTERNAL 6** |

BLOCKED, SKIP and EXTERNAL are **not** passes.

## Documents supplied and what they could support

| File | Finding |
|---|---|
| `standard_iso_9613-2_2024.pdf` | scan (no text layer). Equations (3)-(25), (31), (32), Tables 2-3 read from page images; citations in `FORMULA_MATRIX.md` |
| `ISO 9613-2 2024 DAmd 1.PNG` | screenshot with **only** eqs. (18) and (21). Draft mode is limited to those two |
| `ISO_TR 17534-3_2015.pdf` | text layer present. Contains T01-T19 with reference results. **Targets ISO 9613-2:1996** |
| `ISO_TR 17534-2_2015.pdf` | general QA recommendations (Part 2), not the 9613-2 benchmarks. Not used as numerical reference |
| `ISO_TR 17534-1_2015.pdf` | the file name says TR, but it is the full standard BS ISO 17534-1:2015 (quality requirements) |
| `ISO 9613-1 1993.pdf` | scan; the **last four pages are an unrelated document (ISO 5077, textiles)** appended to the file. Table 1(a) used as golden data |

## Group results

### G1 Analytic (23 tests, all PASS)
A_div, energy sums, exact band centres, A_gr limits (hard ground -6 dB, porous ground 0 dB), K_geo, D_z hand value, caps, continuity at z_min, A_bar combination and the Formulae (16)/(17) switch, C_met, mass law (value and slope), effective TL with openings, enclosure formula, background subtraction, 2D geometry (ridge, flat, negative z), compliance logic, octave-filter tone level, factor-8 rule. Expected values are hand derivations or documented limits, never taken from the function under test.

### G2 Independent numerical reference (4 tests, 44 values, all PASS)
`A_atm` against **ISO 9613-1:1993 Table 1(a)** (-20 degC, 101.325 kPa, 63 / 125 / 250 / 315 Hz exact third-octave centres, RH 10-100 %). Tolerance 0.8 % of each printed value (3 significant digits). This independently confirms the ISO 9613-1 implementation and the exact-centre-frequency rule of 9613-2:2024 cl. 7.2. Higher temperatures than -20 degC were not tabulated in the read pages and are not covered by this group.

### G3 ISO/TR 17534-3:2015 (19 cases): 15 PASS, 4 BLOCKED, run in the `iso1996` mode

| Case | Result | Rows | Max abs error (dB) |
|---|---|---|---|
| T01 reflecting ground | PASS | 18/18 | 0.004 |
| T02 mixed ground | PASS | 18/18 | 0.004 |
| T03 porous ground | PASS | 18/18 | 0.004 |
| T04 varying ground factor | PASS | 21/21 | 0.005 |
| T05 as T04, simplified ground method | PASS | 18/18 | 0.005 |
| T06 varying height/properties (geometry as tabulated) | PASS | 18/18 | 0.004 |
| T07 as T06, simplified method (h_m as tabulated) | PASS | 18/18 | 0.007 |
| T08 long barrier | PASS | 26/26 | 0.009 |
| T09 short barrier | PASS | 26/26 | 0.005 |
| T10 | **BLOCKED** | | |
| T11 cubic building, low receiver | PASS | 26/26 | 0.004 |
| T12 cubic building, high receiver | PASS | 26/26 | 0.004 |
| T13 polygonal building | PASS | 26/26 | 0.004 |
| T14 | **BLOCKED** | | |
| T15 polygonal building, high receiver | PASS | 26/26 | 0.005 |
| T16 three buildings | PASS | 26/26 | 0.005 |
| T17 three buildings, other positions | PASS | 26/26 | 0.005 |
| T18 | **BLOCKED** | | |
| T19 | **BLOCKED** | | |

Tolerance is the TR's own: +-0.05 dB for band values and totals. Rows compare unweighted band levels, A-weighted band levels, both totals and (where tabulated) the combined `A_bar`; T04 also compares `G_s`, `G_m`, `G_r`.

Blocked cases and why:
- **T10, T14**: need a ground surface built from the contour-line rectangles of Table 12/13, and (T10) a barrier with a sloping top edge. The TR does not define how the surface between contours is constructed, so no unambiguous terrain exists. T06/T07 run with their tabulated heights and elevation difference instead (the surface itself is not reconstructed; they verify the attenuation chain, not terrain construction).
- **T18**: the text layer of the footprint table is scrambled and cannot be read back reliably, and the shortest paths around a concave footprint with a courtyard need a visibility-graph search that is not implemented.
- **T19**: needs reflections from obstacle surfaces (ISO 9613-2 7.5, image sources), not implemented.

**Important caveat on G3.** The benchmark was used to *find and fix* defects, and four model decisions were derived from the TR's published ray geometry and reference levels:
1. lateral paths use the obstacle cross-section clipped at the roof height in the tilted lateral plane (T12, T15);
2. obstacles that do not block the direct ray but lie in the way of the left/right string are added (T17);
3. `lambda` for the 63 Hz band is 340/62.5 in 1996 mode (T16);
4. the factor-8 rule is not applied in 1996 mode (T09).
The ray-geometry values (`d_ss`, `d_sr`, `e`, `z`) of T15 and T16 agreed with the published tables independently of the final levels, which is the stronger evidence; the final level agreement is partly by construction. Items 3 and 4 affect only `iso1996`; items 1 and 2 also apply to the 2024 mode, where the standard text does not say how the construction is done.

### G4 ISO 9613-2:2024 (3 PASS, 1 SKIP)
Table 3 expressions `a'`..`d'` against the values printed in the TR (same expressions), 2024-versus-1996 `A_gr` agreement. **The full 2024 chain has "independent benchmark unavailable"** (SKIP): no published reference results for the 2024 edition were supplied. Full-standard conformance is not asserted.

### G5 DRAFT-AMENDMENT regression (5 tests, all PASS)
Positive/zero/negative `z`, `z_min` boundary, `K_met` restrictions, lateral `K_met = 1`, and that draft and published forms differ. Labelled DRAFT and kept apart from G4.

### G6 Integration (6 groups, EXTERNAL in the app; verified by pytest)
Hot reload (edit a copy of the library in a running MATLAB session; next result changes by exactly the edit; old cache invalidated; revert restores), API scenarios, DEM import (ESRI ASCII, XYZ, GeoTIFF projected and geographic reprojection), audio pipeline, projects/cases/persistence/Excel, compliance logic. Counts: 193 tests in total.

## The ten acceptance scenarios

| # | Scenario | Evidence |
|---|---|---|
| 1 | Flat ground, manual spectrum, one receiver | `test_e2e_acceptance.py::test_1`; `A_div` 54.52 dB at 150 m checked by hand; broadband = energy sum |
| 2 | 2D ridge, visible path, barrier terms | `test_2`; path list `[S, crest, R]`, `A_bar_top` > 5 dB; UI checked in the browser (map, contours, click inspector) |
| 3 | 3D DEM, surface-following grid, contour map | `test_3` (ESRI ASCII upload); UI checked in the browser (map and 3D surface) |
| 4 | Finite wall, top and lateral paths, inspected | `test_4`; UI path table checked in the browser (top blocked z = 0.159 m, both lateral paths used) |
| 5 | Light fabric screen, assumptions reported | `test_5`: TL, A_eff, opaque A_bar, warning "below 10 kg/m2", "NOT prescribed by ISO" |
| 6 | Calibrated audio, uncalibrated error path | `test_6` (calibrator, background, L_W; no calibration -> HTTP 422 "No calibration") |
| 7 | One project, many cases, one workbook | `test_7`: Summary + one sheet per case; formula-injection-safe text; live difference formulas |
| 8 | Per-band compliance map | `test_8`: red points exist that pass the overall dB(A) limit but exceed 500 Hz; UI checked in the browser (exceeding bands highlighted) |
| 9 | Supported benchmarks from the application | `test_9` and the Test Lab (T01-T09, T11-T13, T15-T17 PASS; four BLOCKED) |
| 10 | Edited MATLAB file changes the next run | `test_hot_reload.py` (5 tests) |

## Browser checks performed (manual, Chrome)
Flat point case, 2D section (map, contours, PASS/FAIL layer, click inspector with exceeding bands in red), 3D terrain (map, 3D surface, obstacle editor, path inspector with top and lateral paths), Test Lab (run all, detail with geometry plot), MATLAB diagnostics.

Added later and checked in a browser: Projects -> Open in view for a loaded ISO/TR case (T11): the scene, 1996 mode, obstacle and receivers restored, map and colours produced, a clicked point shows its top and lateral paths, and Save changes and rerun updates the stored case.

GUI redesign (presentation layer only; `matlab/`, `backend/`, `tests/`, `api.ts` and the request-building code are unchanged). Checked in a browser, light and dark: flat-ground run by Ctrl+Enter, command-palette jump to a parameter, edit then Undo (value and "edited" marker restored), 3D terrain with a wall (map, contours, click-to-inspect, path inspector, sticky run bar), Test Lab run all (PASS 50, FAIL 0, BLOCKED 4, SKIP 1, EXTERNAL 6, identical to before the redesign). Pytest before the redesign: 186 passed with the hot-reload tests deselected. Known gap: Plotly figures take their colours from the theme when drawn, so after switching theme an already drawn plot keeps the old colours until it is redrawn (rerun). Presets, undo history and layout live in browser storage only.

**Not exercised in a browser**: "Save as case" from a fresh scene, the audio page (file chooser and waveform selection), the fabric-screen and enclosure panels, the PNG export buttons, the watch-mode checkbox. They are covered by API tests where noted but their UI behaviour was only type-checked and built.

## What is approximate or unsupported
- Not implemented: reflections (7.5), `A_misc` (foliage, industrial sites, housing), chimney directivity, multi-source, FAST geometry mode, parallel evaluation, rubber-band paths around concave footprints, screens with arbitrary polygons (walls and rectangles only), hills with lateral paths.
- Octave filters are a custom Butterworth bank (`nb_butter_sos`, base MATLAB), not verified for IEC 61260-1. Verified by tone and white-noise tests, by analytic Butterworth properties (-3.0103 dB at the edges), and against `butter`+`zp2sos` (worst response difference 3e-8 dB over 39 filters at 22.05-96 kHz) and scipy (< 1e-6 dB). A MATLAB session with the path restricted to base MATLAB (no `butter`) passed the audio, analytic and two ISO/TR benchmark tests.
- The A-weighting vector is the one supplied in the brief (octave-band values of IEC 61672-1; ISO 9613-2 cites that standard but the supplied scan does not tabulate it).
- `A_atm` is verified only against Table 1(a) at -20 degC, not at typical weather; the 1996 mode supports only 20 degC / 70 %.
- GeoTIFF reprojection was tested with synthetic rasters, not survey data.
- Transmission through a fabric, mass law, enclosures and the under-gap path are engineering approximations, not ISO methods.
- The 3D view uses Plotly WebGL surfaces (reused dependency), not three.js or MapLibre.
- Excel export has no embedded charts; map export is a PNG download of the on-screen plot.
- Hebrew localisation and RTL are not implemented (labels are plain strings and the page has `dir="ltr"`).
- No Claude skills, MCP servers or other tools were installed: none was authorised, and built-in tools sufficed.
- `setup_windows.ps1` was assembled from steps run by hand and not executed as a script. `setup.sh` / `start.sh` for macOS and Linux are untested.
