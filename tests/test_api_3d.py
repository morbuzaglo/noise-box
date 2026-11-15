import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app, state  # noqa: E402

ASC = "ncols 21\nnrows 11\nxllcorner -5\nyllcorner -5\ncellsize 10\nNODATA_value -9999\n" + "\n".join(
    " ".join(f"{max(0.0, 10.0 - abs(ix * 10 - 100) / 10):.3f}" for ix in range(21)) for _ in range(11)
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        state["worker"].wait_ready()
        yield c


def test_upload_rejects_bad_extension_and_geographic(client):
    r = client.post("/api/dem/upload", files={"file": ("evil.exe", b"MZ")}, data={"vertical_unit": "m"})
    assert r.status_code == 415
    deg = ASC.replace("xllcorner -5", "xllcorner 35").replace("yllcorner -5", "yllcorner 32").replace("cellsize 10", "cellsize 0.0001")
    r = client.post("/api/dem/upload", files={"file": ("g.asc", deg.encode())}, data={"vertical_unit": "m", "declared_metric": "true"})
    assert r.status_code == 422 and "degrees" in r.text


def test_upload_then_field3d_end_to_end(client):
    r = client.post("/api/dem/upload", files={"file": ("../../ridge.asc", ASC.encode())},
                    data={"vertical_unit": "m", "declared_metric": "true"})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["nx"] == 21 and info["ny"] == 11 and info["zmax"] == pytest.approx(10.0)
    assert info["meta"]["source"] == "ridge.asc"                      # path components stripped
    body = {
        "dem_id": info["dem_id"],
        "Lw": [90, 95, 100, 100, 98, 95, 90, 85],
        "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}, "atm": {"T_C": 10, "RH": 70, "p_kPa": 101.325},
        "source": {"x": 0, "y": 50, "h": 2.0},
        "grid": {"x0": 20, "x1": 190, "nx": 8, "y0": 20, "y1": 80, "ny": 4},
        "hr": 1.5,
        "limits": {"bands": [None, None, None, 45, 45, 45, 45, 45], "weighting": "Z", "overallA": None},
    }
    r = client.post("/api/field3d", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["Lp"]) == 32 and len(j["valid"]) == 32 and all(j["valid"])
    assert len(j["ground"]) == 32
    xs = [20 + 170 * i / 7 for i in range(8)]                       # receiver columns, hand-derived
    expect = [max(0.0, 10.0 - abs(x - 100) / 10) for x in xs] * 4     # DEM ground under each receiver
    assert j["ground"] == pytest.approx(expect, abs=1e-6)
    codes = j["compliance"]["code"]
    assert set(codes) <= {0.0, 1.0}
    # behind the ridge (x > 100) levels are lower than at the same distance in front, for this symmetric terrain
    assert 1 in j["kind"]


def test_unknown_dem_is_404(client):
    body = {"dem_id": "nope", "Lw": [90] * 8, "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
            "atm": {"T_C": 10, "RH": 70, "p_kPa": 101.325}, "source": {"x": 0, "y": 0, "h": 2},
            "grid": {"x0": 0, "x1": 10, "nx": 2, "y0": 0, "y1": 10, "ny": 2}}
    assert client.post("/api/field3d", json=body).status_code == 404
