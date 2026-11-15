import os, pathlib, sys, tempfile
import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.main import app, state  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        state["worker"].wait_ready()
        yield c


def test_catalog_has_all_groups_and_nineteen_benchmarks(client):
    cat = client.get("/api/testlab/catalog").json()
    groups = {r["group"][:2] for r in cat}
    assert groups == {"G1", "G2", "G3", "G4", "G5", "G6"}
    assert sorted(r["id"] for r in cat if r["id"].startswith("G3-")) == [f"G3-T{k:02d}" for k in range(1, 20)]
    assert all(r["source"] for r in cat)                                   # every test names its documentary source


def test_run_group3_reports_pass_blocked_and_never_counts_blocked_as_pass(client):
    j = client.post("/api/testlab/run", json={"group": "G3"}).json()
    st = {r["id"]: r["status"] for r in j["results"]}
    assert st["G3-T08"] == "PASS" and st["G3-T17"] == "PASS"
    blocked = {k for k, v in st.items() if v == "BLOCKED"}
    assert blocked == {"G3-T10", "G3-T14", "G3-T18", "G3-T19"}
    assert j["counts"]["PASS"] == 15 and j["counts"]["BLOCKED"] == 4
    t8 = next(r for r in j["results"] if r["id"] == "G3-T08")
    assert t8["n"] == 26 and t8["n_pass"] == 26 and t8["max_abs_error"] < 0.05
    assert "nb_receiver_3d" in t8["calls"]                                  # names the production functions it exercised


def test_every_row_carries_expected_actual_error_tolerance(client):
    j = client.post("/api/testlab/run", json={"ids": ["G1-adiv", "G2-atm-f63", "G4-chain-2024"]}).json()
    by = {r["id"]: r for r in j["results"]}
    r = by["G2-atm-f63"]
    assert r["n"] == 11 and len(r["tol"]) == 11 and len(r["err"]) == 11 and len(r["labels"]) == 11
    assert by["G4-chain-2024"]["status"] == "SKIP" and "unavailable" in by["G4-chain-2024"]["detail"]


def test_reports_are_exportable(client):
    client.post("/api/testlab/run", json={"ids": ["G1-adiv", "G5-lateral"]})
    j = client.get("/api/testlab/report.json")
    assert j.status_code == 200 and j.json()["counts"]["PASS"] == 2
    md = client.get("/api/testlab/report.md").text
    assert "not an ISO certification" in md and "G1-adiv" in md


def test_load_benchmark_as_editable_case_and_rerun(client):
    p = client.post("/api/projects", json={"name": "bench"}).json()
    r = client.post("/api/testlab/G3-T11/load", json={"project_id": p["id"]})
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["input"]["request"]["mode"] == "iso1996" and len(case["input"]["request"]["obstacles"]) == 1
    done = client.post(f"/api/cases/{case['id']}/run").json()
    rec = done["result"]["receivers"][0]
    # T11 reference (ISO/TR 17534-3 Table 31): total L = 51.81 dB -> energy sum of the band levels
    import math
    tot = 10 * math.log10(sum(10 ** (v / 10) for v in rec["out"]["Lp"]))
    assert tot == pytest.approx(51.81, abs=0.05)
    assert client.post(f"/api/testlab/G3-T06/load", json={"project_id": p["id"]}).status_code == 422     # tabulated geometry
    assert client.post(f"/api/testlab/G3-T10/load", json={"project_id": p["id"]}).status_code == 422     # blocked


def test_stored_terrain_case_restores_its_dem_for_editing(client):
    p = client.post("/api/projects", json={"name": "reopen"}).json()
    case = client.post("/api/testlab/G3-T08/load", json={"project_id": p["id"]}).json()
    d = client.get(f"/api/cases/{case['id']}/dem")
    assert d.status_code == 200, d.text
    j = d.json()
    assert j["cs"] == 10.0 and j["nx"] > 20 and j["ny"] > 20 and j["meta"]["source"] == "synthetic:flat"
    # the restored id works with the live 3D endpoint, i.e. the case can be edited and rerun like a fresh scene
    req = case["input"]["request"]
    body = {**req, "dem_id": j["dem_id"], "grid": {"x0": req["grid"]["x0"] + 100, "x1": req["grid"]["x0"] + 180, "nx": 3, "y0": req["grid"]["y0"] + 100, "y1": req["grid"]["y0"] + 160, "ny": 3}}
    r = client.post("/api/field3d", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["nObstacles"] == 1
    point = client.post("/api/cases/nope/dem")
    assert point.status_code in (404, 405)
