"""End-to-end acceptance scenarios (brief, 'Final delivery'), through the HTTP API with real MATLAB.

Scenario 10 (MATLAB hot reload) is verified in test_hot_reload.py against an isolated copy of the library.
"""
import io
import math
import os
import pathlib
import sys
import tempfile


import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

import make_samples  # noqa: E402
from app.main import app, state  # noqa: E402

LW = [90, 95, 100, 100, 98, 95, 90, 85]
G = {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}
ATM = {"T_C": 10, "RH": 70, "p_kPa": 101.325}


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples")
    make_samples.make(d)
    return d


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        state["worker"].wait_ready()
        yield c


def esum(v):
    return 10 * math.log10(sum(10 ** (x / 10) for x in v))


def test_1_flat_ground_manual_spectrum_one_receiver(client):
    j = client.post("/api/run", json={"Lw": LW, "hs": 2, "hr": 1.5, "dp": 150, "G": G, "atm": ATM}).json()
    d = math.hypot(150, 0.5)
    assert j["d"] == pytest.approx(d)
    assert all(a == pytest.approx(20 * math.log10(d) + 11, abs=1e-9) for a in j["Adiv"])
    assert j["Lp_broadband"] == pytest.approx(esum(j["Lp"]), abs=1e-9)                 # energy sum of the 8 bands
    assert j["LpA_broadband"] == pytest.approx(esum(j["LpA_bands"]), abs=1e-9)
    assert j["Cmet"] == 0.0 and len(j["Agr"]) == 8


def test_2_ridge_section_with_path_and_barrier_contributions(client):
    prof = [(0, 0), (100, 10), (200, 0)]
    body = {"Lw": LW, "G": G, "atm": ATM, "terrain": {"x": [p[0] for p in prof], "z": [p[1] for p in prof]}, "source_x": 0, "source_h": 2,
            "grid": {"x0": 10, "x1": 190, "nx": 10, "z0": 0, "z1": 20, "nz": 5}}
    f = client.post("/api/field2d", json=body).json()
    assert 1 in f["kind"] and max(max(r) for r in f["Abar"] if r[0] is not None) > 5
    p = client.post("/api/projects", json={"name": "e2e"}).json()
    c = client.post(f"/api/projects/{p['id']}/cases", json={"name": "Ridge", "kind": "section", "input": {"request": body, "receivers": [{"name": "Behind", "x": 150, "h": 1.5}], "run_field": False}}).json()
    r = client.post(f"/api/cases/{c['id']}/run").json()["result"]["receivers"][0]
    assert r["geom"]["kind"] == "blocked" and r["geom"]["z"] > 0 and len(r["geom"]["path"]) == 3        # visible path with the crest as an edge
    assert max(r["out"]["Abar"]) > 5 and max(r["out"]["Abar_top"]) > 5


def test_3_dem_upload_surface_following_grid_and_contours(client, samples):
    up = client.post("/api/dem/upload", files={"file": ("ridge.asc", (samples / "terrain" / "ridge_dem.asc").read_bytes())}, data={"vertical_unit": "m", "declared_metric": "true"}).json()
    assert up["nx"] == 61 and up["zmax"] == pytest.approx(10.0)
    body = {"dem_id": up["dem_id"], "Lw": LW, "G": G, "atm": ATM, "source": {"x": 20, "y": 150, "h": 2}, "hr": 1.5,
            "grid": {"x0": 30, "x1": 280, "nx": 11, "y0": 50, "y1": 250, "ny": 5}}
    f = client.post("/api/field3d", json=body).json()
    assert all(f["valid"]) and max(f["ground"]) == pytest.approx(10.0, abs=1.0) and min(f["ground"]) == pytest.approx(0.0, abs=1e-9)
    lpa = f["LpA_broadband"]
    assert max(lpa) - min(lpa) > 10                                                    # a map with usable contrast for contours
    assert 1 in f["kind"]                                                              # some receivers are in the ridge shadow


def _dem(client, kind="flat"):
    return client.post("/api/dem/synthetic", json={"kind": kind, "nx": 41, "ny": 41, "cs": 10}).json()["dem_id"]


def test_4_finite_wall_top_and_lateral_paths(client):
    did = _dem(client)
    b = {"dem_id": did, "Lw": LW, "G": G, "atm": ATM, "source": {"x": 100, "y": 200, "h": 2}, "receiver": {"x": 300, "y": 200, "h": 1.5},
         "obstacles": [{"kind": "wall", "x": [200, 200], "y": [190, 210], "h": 5}]}
    j = client.post("/api/case3d", json=b).json()
    assert j["geom"]["kind"] == "blocked" and j["geom"]["lateral"]["left"]["valid"] and j["geom"]["lateral"]["right"]["valid"]
    assert len(j["paths"]["top"]) == 3 and len(j["paths"]["left"]) == 3 and len(j["paths"]["right"]) == 3   # paths returned for display
    ab = j["out"]
    assert all(c <= t + 1e-9 for c, t in zip(ab["Abar"], ab["Abar_top"]))               # lateral energy can only lower A_bar


def test_5_light_fabric_screen_reports_assumptions(client):
    did = _dem(client)
    b = {"dem_id": did, "Lw": LW, "G": G, "atm": ATM, "source": {"x": 100, "y": 200, "h": 2}, "receiver": {"x": 300, "y": 200, "h": 1.5},
         "obstacles": [{"kind": "wall", "x": [200, 200], "y": [190, 210], "h": 5, "material": {"surface_mass": 0.4}}]}
    s = client.post("/api/case3d", json=b).json()["out"]["screen"]
    assert "NOT prescribed by ISO" in s["method"]
    assert any("10 kg/m^2" in w for w in s["info"]["warnings"]) and any("mass-law" in m for m in s["info"]["materials"])
    assert len(s["TL"]) == 8 and len(s["A_eff"]) == 8 and len(s["Abar_opaque"]) == 8 and len(s["L_transmitted"]) == 8
    assert all(e <= o + 1e-9 for e, o in zip(s["A_eff"], s["Abar_opaque"]))


def test_6_calibrated_audio_and_the_uncalibrated_error_path(client, samples):
    def up(name):
        return client.post("/api/audio/upload", files={"file": (name, (samples / "audio" / name).read_bytes())}).json()["audio_id"]

    cal, mach, bg = up("calibrator_94dB_1kHz.wav"), up("machine_example.wav"), up("background_example.wav")
    est = {"hs": 1.5, "hm": 1.2, "dp": 10, "dh": 0, "G": G, "atm": ATM}
    body = {"signal": {"audio_id": mach, "start": 2, "stop": 10},
            "calibration": {"mode": "calibrator", "calibrator": {"audio_id": cal, "start": 1, "stop": 6, "level": 94, "freq": 1000}},
            "background": {"audio_id": bg, "start": 1, "stop": 6}, "estimate": est}
    r = client.post("/api/audio/analyze", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["absolute"] and len(j["L"]) == 8 and len(j["lw"]["Lw"]) == 8
    assert j["calibration"]["paPerUnit"] == pytest.approx(20e-6 * 10 ** (94 / 20) / 0.05, rel=3e-3)
    assert j["subtraction"]["status"][4] in ("ok", "marginal")
    bad = client.post("/api/audio/analyze", json={"signal": {"audio_id": mach, "start": 2, "stop": 10}, "estimate": est})
    assert bad.status_code == 422 and "No calibration" in bad.text                    # blocked, not guessed


def test_7_multi_case_project_exports_one_workbook_one_sheet_per_case(client):
    p = client.post("/api/projects", json={"name": "Multi"}).json()
    base = {"Lw": LW, "hs": 2, "hr": 1.5, "dp": 150, "G": G, "atm": ATM, "limits": {"bands": [None, None, None, 45, 45, 45, 45, 45], "weighting": "Z", "overallA": None}}
    names = ["Cold", "Hot", "Draft check"]
    atm = [{"T_C": 0, "RH": 70, "p_kPa": 101.325}, {"T_C": 35, "RH": 40, "p_kPa": 101.325}, ATM]
    for nm, a in zip(names, atm):
        c = client.post(f"/api/projects/{p['id']}/cases", json={"name": nm, "kind": "point", "input": {"request": {**base, "atm": a, "mode": "draft2026" if nm == "Draft check" else "iso2024"}, "receivers": [{"name": "R1"}]}}).json()
        client.post(f"/api/cases/{c['id']}/run")
    wb = load_workbook(io.BytesIO(client.get(f"/api/projects/{p['id']}/export.xlsx").content))
    assert wb.sheetnames == ["Summary"] + names
    text = "\n".join(str(c.value) for row in wb["Draft check"].iter_rows() for c in row if c.value is not None)
    assert "DRAFT" in text                                                              # draft mode is labelled in the workbook


def test_8_one_exceeded_band_turns_the_receiver_red_even_if_dba_passes(client):
    body = {"Lw": LW, "G": G, "atm": ATM, "terrain": {"x": [0, 200], "z": [0, 0]}, "source_x": 0, "source_h": 2,
            "grid": {"x0": 20, "x1": 190, "nx": 18, "z0": 1.5, "z1": 1.5001, "nz": 2},
            "limits": {"bands": [None, None, None, 45, None, None, None, None], "weighting": "Z", "overallA": 80}}      # only 500 Hz limited, loose dB(A) limit
    f = client.post("/api/field2d", json=body).json()
    codes, lpa = f["compliance"]["code"], f["LpA_broadband"]
    assert 0.0 in codes and 1.0 in codes                                                # both red and green points exist
    red = [i for i, c in enumerate(codes) if c == 0.0]
    assert all(lpa[i] < 80 for i in red)                                                # these points pass the overall dB(A) limit
    assert all(f["compliance"]["exceed"][i][3] for i in red)                            # because the 500 Hz band exceeds its own limit
    assert not any(f["compliance"]["overallExceed"][i] for i in red)


def test_9_benchmarks_run_from_the_application(client):
    j = client.post("/api/testlab/run", json={"group": "G3"}).json()
    assert j["counts"] == {"PASS": 15, "BLOCKED": 4}
