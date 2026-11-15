import pathlib
import sys
import time

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app, state  # noqa: E402

REQ = {
    "Lw": [90, 95, 100, 100, 98, 95, 90, 85],
    "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
    "atm": {"T_C": 10, "RH": 70, "p_kPa": 101.325},
    "terrain": {"x": [0, 100, 200], "z": [0, 10, 0]},
    "source_x": 0, "source_h": 2,
    "grid": {"x0": 5, "x1": 195, "nx": 40, "z0": 0, "z1": 30, "nz": 20},
    "limits": {"bands": [60, 60, 55, 50, 45, 45, 45, 45], "weighting": "Z", "overallA": None},
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        state["worker"].wait_ready()
        yield c


def test_field_endpoint_shapes_and_masking(client):
    t = time.time()
    r = client.post("/api/field2d", json=REQ)
    dt = time.time() - t
    assert r.status_code == 200, r.text
    j = r.json()
    n = 40 * 20
    assert len(j["Lp"]) == n and len(j["Lp"][0]) == 8
    assert len(j["valid"]) == n
    assert any(j["valid"]) and not all(j["valid"])      # some masked (inside ridge / below ground)
    # masked points are null (no data), never a number
    k = j["valid"].index(False)
    assert all(v is None for v in j["Lp"][k])
    print(f"field 40x20 = {n} points in {dt:.1f} s")
    assert dt < 120


def test_grid_size_limit(client):
    bad = dict(REQ, grid=dict(REQ["grid"], nx=400, nz=400))
    assert client.post("/api/field2d", json=bad).status_code == 422
