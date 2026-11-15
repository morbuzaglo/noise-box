"""API smoke tests: validation and the end-to-end flat-ground case via FastAPI + MATLAB."""
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app, state  # noqa: E402

BODY = {
    "Lw": [90, 95, 100, 100, 98, 95, 90, 85],
    "hs": 2.0, "hr": 1.5, "dp": 150.0,
    "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
    "atm": {"T_C": 10, "RH": 70, "p_kPa": 101.325},
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        state["worker"].wait_ready()
        yield c


def test_health_and_registry(client):
    h = client.get("/api/health").json()
    assert h["matlab"] == "ready"
    names = {f["name"] for f in client.get("/api/functions").json()}
    assert "run_acoustic_case" in names


def test_run_returns_eight_band_terms(client):
    r = client.post("/api/run", json=BODY)
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ("Adiv", "Aatm", "Agr", "Abar", "Atotal", "Lp", "LpA_bands"):
        assert len(j[k]) == 8
    assert j["Lp_broadband"] > max(j["Lp"])
    assert j["Cmet"] == 0.0


def test_rejects_wrong_band_count(client):
    bad = dict(BODY, Lw=[90.0] * 7)
    assert client.post("/api/run", json=bad).status_code == 422


def test_rejects_g_out_of_range(client):
    bad = dict(BODY, G={"Gs": 1.5, "Gm": 0.5, "Gr": 0.5})
    assert client.post("/api/run", json=bad).status_code == 422


def test_draft_mode_is_labelled_and_differs(client):
    barrier = {"z": 0.5, "dss": 75.0, "dsr": 75.0, "e": 0.0}
    a = client.post("/api/run", json=dict(BODY, barrier=barrier)).json()
    b = client.post("/api/run", json=dict(BODY, barrier=barrier, mode="draft2026")).json()
    assert a["mode"] == "iso2024" and b["mode"] == "draft2026"
    assert a["Abar"] != b["Abar"]
