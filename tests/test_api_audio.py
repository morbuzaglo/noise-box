import io
import math
import pathlib
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.io import wavfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app, state  # noqa: E402

FS = 44100


def wav_bytes(x, fs=FS):
    b = io.BytesIO()
    wavfile.write(b, fs, x.astype(np.float32))
    return b.getvalue()


def tone(f, rms, seconds=8.0):
    t = np.arange(int(FS * seconds)) / FS
    return rms * math.sqrt(2) * np.sin(2 * math.pi * f * t)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        state["worker"].wait_ready()
        yield c


def upload(client, x, name="rec.wav"):
    r = client.post("/api/audio/upload", files={"file": (name, wav_bytes(x))})
    assert r.status_code == 200, r.text
    return r.json()


EST = {"hs": 1.5, "hm": 1.2, "dp": 30.0, "dh": 0.0, "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
       "atm": {"T_C": 15, "RH": 60, "p_kPa": 101.325}}


def test_upload_metadata_waveform_and_stream(client):
    info = upload(client, tone(1000.0, 0.1))
    assert info["fs"] == FS and info["channels"] == 1 and info["duration"] == pytest.approx(8.0, abs=1e-3)
    assert "path" not in info                                          # server paths are never exposed
    w = client.get(f"/api/audio/{info['audio_id']}/waveform?points=400").json()
    assert len(w["t"]) == 400 and max(w["max"]) == pytest.approx(0.1 * math.sqrt(2), abs=0.01)
    f = client.get(f"/api/audio/{info['audio_id']}/file")
    assert f.status_code == 200 and f.headers["content-type"] == "audio/wav" and f.content[:4] == b"RIFF"


def test_rejects_wrong_type_and_garbage(client):
    assert client.post("/api/audio/upload", files={"file": ("x.exe", b"MZ")}).status_code == 422
    assert client.post("/api/audio/upload", files={"file": ("x.wav", b"not audio at all")}).status_code == 422
    assert client.get("/api/audio/deadbeef/file").status_code == 404


def test_interval_validation(client):
    a = upload(client, tone(1000.0, 0.1))["audio_id"]
    bad = {"signal": {"audio_id": a, "start": 3.0, "stop": 3.05}}
    assert client.post("/api/audio/analyze", json=bad).status_code == 422                  # < 0.1 s
    far = {"signal": {"audio_id": a, "start": 2.0, "stop": 30.0}}
    assert client.post("/api/audio/analyze", json=far).status_code == 422                  # beyond the file


def test_uncalibrated_analysis_is_relative_and_blocks_lw(client):
    a = upload(client, tone(1000.0, 0.1))["audio_id"]
    ok = client.post("/api/audio/analyze", json={"signal": {"audio_id": a, "start": 2.0, "stop": 7.0}})
    assert ok.status_code == 200, ok.text
    j = ok.json()
    assert j["absolute"] is False and "UNCALIBRATED" in j["signal"]["unit"]
    assert j["L"][4] == pytest.approx(20 * math.log10(0.1), abs=0.15)
    blocked = client.post("/api/audio/analyze", json={"signal": {"audio_id": a, "start": 2.0, "stop": 7.0}, "estimate": EST})
    assert blocked.status_code == 422 and "No calibration" in blocked.text


def test_calibrator_mode_gives_absolute_levels_and_lw(client):
    cal = upload(client, tone(1000.0, 0.05), "cal.wav")["audio_id"]
    sig = upload(client, tone(1000.0, 0.10), "sig.wav")["audio_id"]
    body = {
        "signal": {"audio_id": sig, "start": 2.0, "stop": 7.0},
        "calibration": {"mode": "calibrator", "calibrator": {"audio_id": cal, "start": 1.0, "stop": 6.0, "level": 94, "freq": 1000}},
        "estimate": EST,
    }
    r = client.post("/api/audio/analyze", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["absolute"] is True
    assert j["L"][4] == pytest.approx(94 + 20 * math.log10(2), abs=0.15)
    assert len(j["lw"]["Lw"]) == 8 and any("one microphone" in w for w in j["lw"]["warnings"])


def test_calibration_modes_need_their_data(client):
    a = upload(client, tone(1000.0, 0.1))["audio_id"]
    sig = {"audio_id": a, "start": 2.0, "stop": 7.0}
    assert client.post("/api/audio/analyze", json={"signal": sig, "calibration": {"mode": "sensitivity"}}).status_code == 422
    assert client.post("/api/audio/analyze", json={"signal": sig, "calibration": {"mode": "calibrator"}}).status_code == 422


def test_sample_rate_mismatch_is_rejected(client):
    a = upload(client, tone(1000.0, 0.1))["audio_id"]
    b = client.post("/api/audio/upload", files={"file": ("lo.wav", wav_bytes(tone(1000.0, 0.1, 6.0)[:16000 * 6], 16000))}).json()["audio_id"]
    body = {"signal": {"audio_id": a, "start": 2.0, "stop": 7.0}, "calibration": {"mode": "sensitivity", "pa_per_unit": 10},
            "background": {"audio_id": b, "start": 1.0, "stop": 4.0}}
    r = client.post("/api/audio/analyze", json=body)
    assert r.status_code == 422 and "sample rate" in r.text
