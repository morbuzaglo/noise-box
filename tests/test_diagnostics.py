import os, pathlib, shutil, sys, tempfile, time
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


def test_diagnostics_reports_matlab_toolboxes_and_requirements(client):
    d = client.get("/api/diagnostics").json()
    assert d["state"] == "ready" and d["matlab"]["release"].startswith("R20")
    tb = dict(zip(d["matlab"]["toolboxes"], d["matlab"]["licensed"]))
    assert tb["Signal Processing Toolbox"] is True                          # needed for the octave filter bank
    assert "MATLAB Runtime" in d["engine_requirement"]


def test_function_registry_has_signature_hash_mtime_and_linked_tests(client):
    rows = {r["name"]: r for r in client.get("/api/functions").json()}
    r = rows["nb_adiv"]
    assert r["signature"].startswith("function A = nb_adiv") and len(r["sha256"]) == 64 and r["mtime"] > 0
    assert "G1-adiv" in r["linked_tests"]
    assert rows["nb_agr"]["linked_tests"]                                   # verified by several tests
    assert "nb_agr" in rows["run_acoustic_case"]["dependencies"]


def test_refresh_button_is_idempotent_and_reports_state(client):
    a = client.post("/api/matlab/refresh").json()
    assert a["reloaded"] is False                                           # nothing changed
    assert client.post("/api/matlab/watch", json={"on": True}).json()["watching"] is True
    assert client.post("/api/matlab/watch", json={"on": False}).json()["watching"] is False
