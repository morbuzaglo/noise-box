import pathlib
import sys

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


def base(client, **wall_extra):
    did = client.post("/api/dem/synthetic", json={"kind": "flat", "nx": 41, "ny": 41, "cs": 10}).json()["dem_id"]
    wall = {"kind": "wall", "x": [200, 200], "y": [190, 210], "h": 5}
    wall.update(wall_extra)
    return {
        "dem_id": did, "Lw": [90, 95, 100, 100, 98, 95, 90, 85],
        "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}, "atm": {"T_C": 10, "RH": 70, "p_kPa": 101.325},
        "source": {"x": 100, "y": 200, "h": 2}, "receiver": {"x": 300, "y": 200, "h": 1.5}, "obstacles": [wall],
    }


def test_light_fabric_screen_reports_assumptions(client):
    r = client.post("/api/case3d", json=base(client, material={"surface_mass": 0.4, "openness": 0.1}))
    assert r.status_code == 200, r.text
    s = r.json()["out"]["screen"]
    assert len(s["TL"]) == 8 and len(s["A_eff"]) == 8
    assert "NOT prescribed by ISO" in s["method"]
    assert any("10 kg/m^2" in w for w in s["info"]["warnings"])
    assert any("mass-law" in m for m in s["info"]["materials"])


def test_measured_tl_and_gap(client):
    b = base(client, material={"TL": [10, 12, 14, 16, 18, 20, 22, 24]}, gap=1.0)
    j = client.post("/api/case3d", json=b).json()
    assert j["geom"]["under"]["present"] is True
    assert j["out"]["screen"]["TL"][0] == pytest.approx(10.0)


def test_material_validation(client):
    assert client.post("/api/case3d", json=base(client, material={})).status_code == 422          # no basis
    assert client.post("/api/case3d", json=base(client, material={"TL": [1, 2, 3]})).status_code == 422
    # volume density of a fabric (solid=False) must be refused by the MATLAB side, not silently multiplied
    r = client.post("/api/case3d", json=base(client, material={"volume_density": 300, "thickness": 0.002}))
    assert r.status_code == 422 and "homogeneous solid" in r.text


def test_enclosure_on_the_point_case(client):
    body = {
        "Lw": [100] * 8, "hs": 2, "hr": 1.5, "dp": 100,
        "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}, "atm": {"T_C": 10, "RH": 70, "p_kPa": 101.325},
        "enclosure": {"S_total": 6, "A_in": 8, "material": {"TL": [20] * 8}},
    }
    j = client.post("/api/run", json=body).json()
    assert all(lw < 100 for lw in j["Lw"])                    # enclosure lowers the radiated power
    assert any("diffuse" in w for w in j["enclosure"]["warnings"])
    bare = client.post("/api/run", json={k: v for k, v in body.items() if k != "enclosure"}).json()
    assert all(a < b for a, b in zip(j["Lp"], bare["Lp"]))
    bad = dict(body, enclosure={"S_total": 6, "A_in": 8, "S_open": 7, "material": {"TL": [20] * 8}})
    assert client.post("/api/run", json=bad).status_code == 422
