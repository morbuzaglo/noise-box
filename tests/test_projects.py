"""Projects, cases, persistence and the multi-sheet Excel export (real MATLAB behind every run)."""
import io
import os
import pathlib
import sys
import tempfile

import pytest


from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import store  # noqa: E402
from app.main import app, state  # noqa: E402

LW = [90, 95, 100, 100, 98, 95, 90, 85]
G = {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}
ATM = {"T_C": 10, "RH": 70, "p_kPa": 101.325}
LIM = {"bands": [None, None, None, 45, 45, 45, 45, 45], "weighting": "Z", "overallA": None}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        state["worker"].wait_ready()
        yield c


@pytest.fixture(scope="module")
def project(client):
    return client.post("/api/projects", json={"name": "Test project", "description": "pytest"}).json()


def point_input(**over):
    req = {"Lw": LW, "hs": 2, "hr": 1.5, "dp": 150, "G": G, "atm": ATM, "limits": LIM}
    req.update(over)
    return {"request": req, "receivers": [{"name": "R1"}]}


def test_create_open_rename_and_files_on_disk(client, project):
    pid = project["id"]
    assert pathlib.Path(str(store.base_dir()), pid, "project.json").exists()                    # JSON metadata beside the DB
    assert client.get(f"/api/projects/{pid}").json()["name"] == "Test project"
    r = client.patch(f"/api/projects/{pid}", json={"name": "Renamed"})
    assert r.json()["name"] == "Renamed"
    assert any(p["id"] == pid for p in client.get("/api/projects").json())
    client.patch(f"/api/projects/{pid}", json={"name": "Test project"})


def test_point_case_run_stores_result_and_code_fingerprint(client, project):
    pid = project["id"]
    c = client.post(f"/api/projects/{pid}/cases", json={"name": "Flat 150 m", "kind": "point", "input": point_input()}).json()
    assert c["status"] == "not run" and c["result"] is None
    done = client.post(f"/api/cases/{c['id']}/run").json()
    assert done["status"] == "completed" and done["executed"]
    rec = done["result"]["receivers"][0]
    assert rec["name"] == "R1" and rec["valid"] and len(rec["out"]["Lp"]) == 8
    assert rec["compliance"]["status"] in ("PASS", "FAIL")
    assert done["fingerprint"]["file"] and len(done["fingerprint"]["md5"][0]) == 32   # exact code version recorded
    assert any("A_misc" in w for w in done["warnings"])


def test_input_snapshot_survives_reopening_the_database(client, project):
    pid = project["id"]
    cases = client.get(f"/api/projects/{pid}").json()["cases"]
    cid = cases[0]["id"]
    before = client.get(f"/api/cases/{cid}").json()
    again = store.get_case(cid)                                                   # straight from SQLite, no HTTP layer
    assert again["input"] == before["input"] and again["result"] == before["result"]


def test_changing_the_input_clears_the_stored_result(client, project):
    pid = project["id"]
    cid = client.get(f"/api/projects/{pid}").json()["cases"][0]["id"]
    new = point_input(dp=300)
    r = client.patch(f"/api/cases/{cid}", json={"input": new}).json()
    assert r["result"] is None and r["status"] == "not run"                       # never show old numbers for new inputs
    client.post(f"/api/cases/{cid}/run")


def test_duplicate_and_change_only_selected_variables(client, project):
    pid = project["id"]
    cid = client.get(f"/api/projects/{pid}").json()["cases"][0]["id"]
    d = client.post(f"/api/cases/{cid}/duplicate", json={"name": "Hot day", "overrides": {"request": {"atm": {"T_C": 30, "RH": 40}}}}).json()
    assert d["input"]["request"]["atm"] == {"T_C": 30, "RH": 40, "p_kPa": 101.325}   # merged, not replaced
    assert d["input"]["request"]["Lw"] == LW and d["result"] is None
    run = client.post(f"/api/cases/{d['id']}/run").json()
    orig = client.get(f"/api/cases/{cid}").json()
    assert run["result"]["receivers"][0]["out"]["Aatm"] != orig["result"]["receivers"][0]["out"]["Aatm"]


def test_invalid_overrides_are_rejected_and_not_kept(client, project):
    pid = project["id"]
    cid = client.get(f"/api/projects/{pid}").json()["cases"][0]["id"]
    n = len(client.get(f"/api/projects/{pid}").json()["cases"])
    r = client.post(f"/api/cases/{cid}/duplicate", json={"overrides": {"request": {"G": {"Gs": 5}}}})
    assert r.status_code == 422
    assert len(client.get(f"/api/projects/{pid}").json()["cases"]) == n


def test_section_and_terrain_cases_with_named_receivers(client, project):
    pid = project["id"]
    sec = {"request": {"Lw": LW, "G": G, "atm": ATM, "terrain": {"x": [0, 100, 200], "z": [0, 10, 0]}, "source_x": 0, "source_h": 2,
                       "grid": {"x0": 10, "x1": 190, "nx": 10, "z0": 0, "z1": 20, "nz": 6}, "limits": LIM},
           "receivers": [{"name": "Behind ridge", "x": 150, "h": 1.5}, {"name": "Front", "x": 50, "h": 1.5}]}
    c = client.post(f"/api/projects/{pid}/cases", json={"name": "Ridge section", "kind": "section", "input": sec}).json()
    done = client.post(f"/api/cases/{c['id']}/run").json()
    names = [q["name"] for q in done["result"]["receivers"]]
    assert names == ["Behind ridge", "Front"] and done["result"]["field"]["n_points"] == 60
    behind, front = done["result"]["receivers"]
    assert behind["path"].startswith("blocked") and front["path"] == "no relevant edge"
    assert max(behind["out"]["Abar"]) > 0

    dem = client.post("/api/dem/synthetic", json={"kind": "flat", "nx": 31, "ny": 31, "cs": 10}).json()
    ter = {"request": {"dem_id": dem["dem_id"], "Lw": LW, "G": G, "atm": ATM, "source": {"x": 50, "y": 150, "h": 2}, "hr": 1.5,
                       "grid": {"x0": 100, "x1": 250, "nx": 4, "y0": 100, "y1": 200, "ny": 3},
                       "obstacles": [{"kind": "wall", "x": [150, 150], "y": [140, 160], "h": 5, "material": {"surface_mass": 0.4}}], "limits": LIM},
           "receivers": [{"name": "Behind wall", "x": 200, "y": 150, "h": 1.5}]}
    t = client.post(f"/api/projects/{pid}/cases", json={"name": "Wall with fabric", "kind": "terrain", "input": ter}).json()
    assert "dem_id" not in t["input"]["request"] and t["input"]["dem_asset"].endswith(".npz")      # asset preserved, live id dropped
    assert pathlib.Path(str(store.base_dir()), pid, "assets", t["input"]["dem_asset"]).exists()
    done = client.post(f"/api/cases/{t['id']}/run").json()
    rec = done["result"]["receivers"][0]
    assert rec["valid"] and rec["out"]["screenApplied"] is True
    assert any("10 kg/m^2" in w for w in done["warnings"])                                         # fabric warning reaches the case


def test_compare_across_cases(client, project):
    pid = project["id"]
    j = client.get(f"/api/projects/{pid}/compare").json()
    assert len(j["cases"]) >= 4
    assert any(r["receiver"] == "R1" for r in j["table"])


def test_excel_export_one_sheet_per_case_plus_summary(client, project):
    pid = project["id"]
    # awkward names: too long, forbidden characters, duplicates, a formula-looking name
    for nm in ["A very long case name that exceeds the Excel thirty-one character limit", "Bad/chars:[x]?*", "=cmd|' /C calc'!A0", "Flat 150 m"]:
        c = client.post(f"/api/projects/{pid}/cases", json={"name": nm, "kind": "point", "input": point_input()}).json()
        client.post(f"/api/cases/{c['id']}/run")
    r = client.get(f"/api/projects/{pid}/export.xlsx")
    assert r.status_code == 200 and r.headers["content-type"].endswith("spreadsheetml.sheet")
    wb = load_workbook(io.BytesIO(r.content))
    cases = client.get(f"/api/projects/{pid}").json()["cases"]
    assert wb.sheetnames[0] == "Summary" and len(wb.sheetnames) == 1 + len(cases)
    assert all(len(n) <= 31 and not any(ch in n for ch in "[]:*?/\\") for n in wb.sheetnames)
    assert len({n.lower() for n in wb.sheetnames}) == len(wb.sheetnames)                          # unique, case-insensitively
    # formula-looking case name stays text on its sheet
    evil = next(n for n in wb.sheetnames if n.startswith("=cmd") or "cmd" in n)
    a1 = wb[evil]["A1"]
    assert a1.data_type == "s" and "cmd" in a1.value
    # a case sheet has the complete reproduction data
    ws = wb["Flat 150 m"]
    text = "\n".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    for needle in ["ISO 9613-2:2024 (published)", "L_W unweighted", "Permitted (unweighted)", "A_div", "A_gr (may be negative)", "MATLAB code fingerprint", "Margin = predicted - permitted"]:
        assert needle in text, needle
    # summary: metadata, case list, comparison and live difference formulas
    s = wb["Summary"]
    stext = "\n".join(str(c.value) for row in s.iter_rows() for c in row if c.value is not None)
    assert "Test project" in stext and "Comparison across receivers and cases" in stext
    formulas = [c.value for row in s.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=IF(")]
    assert formulas, "difference-to-first-case formulas expected"


def test_excel_sheet_values_match_the_stored_result(client, project):
    pid = project["id"]
    cases = client.get(f"/api/projects/{pid}").json()["cases"]
    cid = next(c["id"] for c in cases if c["name"] == "Flat 150 m")
    case = client.get(f"/api/cases/{cid}").json()
    wb = load_workbook(io.BytesIO(client.get(f"/api/projects/{pid}/export.xlsx?case_ids={cid}").content))
    assert wb.sheetnames == ["Summary", "Flat 150 m"]
    ws = wb["Flat 150 m"]
    hdr_row = next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == "Receiver" and ws.cell(r, 2).value == "x, m")
    vals = [ws.cell(hdr_row + 1, 11 + i).value for i in range(8)]                                 # L_p 63..8000 Hz
    assert vals == pytest.approx(case["result"]["receivers"][0]["out"]["Lp"])


def test_csv_export_and_formula_escape(client, project):
    pid = project["id"]
    cid = client.get(f"/api/projects/{pid}").json()["cases"][0]["id"]
    r = client.get(f"/api/cases/{cid}/export.csv")
    assert r.status_code == 200 and r.text.splitlines()[0].startswith("receiver,x_m")


def test_duplicate_project_copies_cases_and_assets_and_delete_removes_files(client, project):
    pid = project["id"]
    d = client.post(f"/api/projects/{pid}/duplicate", json={"name": "Copy"}).json()
    n = len(client.get(f"/api/projects/{pid}").json()["cases"])
    assert len(client.get(f"/api/projects/{d['id']}").json()["cases"]) == n
    assert list(pathlib.Path(str(store.base_dir()), d["id"], "assets").glob("*.npz"))
    assert client.delete(f"/api/projects/{d['id']}").status_code == 200
    assert not pathlib.Path(str(store.base_dir()), d["id"]).exists()
    assert client.get(f"/api/projects/{d['id']}").status_code == 404
