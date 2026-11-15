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


def dem_id(client):
    r = client.post("/api/dem/synthetic", json={"kind": "flat", "nx": 41, "ny": 41, "cs": 10})
    return r.json()["dem_id"]


def body(client, **extra):
    b = {
        "dem_id": dem_id(client), "Lw": [90, 95, 100, 100, 98, 95, 90, 85],
        "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}, "atm": {"T_C": 10, "RH": 70, "p_kPa": 101.325},
        "source": {"x": 100, "y": 200, "h": 2}, "receiver": {"x": 300, "y": 200, "h": 1.5},
        "obstacles": [{"kind": "wall", "x": [200, 200], "y": [190, 210], "h": 5}],
    }
    b.update(extra)
    return b


def test_case3d_returns_paths_and_flags(client):
    r = client.post("/api/case3d", json=body(client))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["valid"] is True
    assert j["geom"]["kind"] == "blocked"
    assert j["geom"]["lateral"]["left"]["valid"] and j["geom"]["lateral"]["right"]["valid"]
    assert len(j["paths"]["top"]) == 3 and len(j["paths"]["left"]) == 3
    assert j["paths"]["top"][1][2] == pytest.approx(5.0)          # 5 m wall on flat 0 m ground
    assert len(j["out"]["Abar_side1"]) == 8 and max(j["out"]["Abar_side1"]) > 0


def test_obstacle_validation(client):
    bad_wall = body(client, obstacles=[{"kind": "wall", "x": [1, 2, 3], "y": [1, 2, 3], "h": 3}])
    assert client.post("/api/case3d", json=bad_wall).status_code == 422
    bad_h = body(client, obstacles=[{"kind": "wall", "x": [1, 2], "y": [1, 2], "h": 0}])
    assert client.post("/api/case3d", json=bad_h).status_code == 422
    tiny = body(client, obstacles=[{"kind": "building", "x": [1, 2], "y": [1, 2], "h": 3}])
    assert client.post("/api/case3d", json=tiny).status_code == 422


def test_receiver_inside_building_reports_reason_not_a_level(client):
    b = body(client, obstacles=[{"kind": "building", "x": [280, 320, 320, 280], "y": [190, 190, 210, 210], "h": 8}])
    j = client.post("/api/case3d", json=b).json()
    assert j["valid"] is False and "inside" in j["reason"]


def test_field3d_accepts_obstacles(client):
    b = body(client)
    b.pop("receiver")
    b["grid"] = {"x0": 250, "x1": 350, "nx": 3, "y0": 190, "y1": 210, "ny": 3}
    b["hr"] = 1.5
    r = client.post("/api/field3d", json=b)
    assert r.status_code == 200, r.text
    assert r.json()["nObstacles"] == 1
