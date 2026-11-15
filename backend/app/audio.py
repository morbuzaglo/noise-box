"""Audio storage and light preprocessing. All acoustic calculation stays in MATLAB.

Uploads are decoded with libsndfile (WAV, FLAC, OGG, and MP3 where libsndfile supports it) and re-stored as
float32 WAV under a random name, so MATLAB reads one known format and no client-supplied path is ever used.
"""
from __future__ import annotations

import os
import pathlib
import uuid

import numpy as np
import soundfile as sf

BASE = pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "NoiseBox" / "audio"
ALLOWED = {".wav", ".flac", ".ogg", ".mp3", ".aif", ".aiff"}
MAX_SECONDS = 1800
AUDIO: dict[str, dict] = {}


class AudioError(ValueError):
    pass


def store(data: bytes, filename: str) -> dict:
    ext = pathlib.Path(filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise AudioError(f"unsupported audio type '{ext}' (allowed: {', '.join(sorted(ALLOWED))})")
    BASE.mkdir(parents=True, exist_ok=True)
    aid = uuid.uuid4().hex
    tmp = BASE / f"{aid}.upload"
    tmp.write_bytes(data)
    try:
        info = sf.info(str(tmp))
        if info.frames / info.samplerate > MAX_SECONDS:
            raise AudioError(f"recording longer than {MAX_SECONDS} s; trim it first")
        x, fs = sf.read(str(tmp), dtype="float32", always_2d=True)
    except AudioError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AudioError(f"could not decode audio: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    path = BASE / f"{aid}.wav"
    sf.write(str(path), x, fs, subtype="FLOAT")
    rec = {
        "audio_id": aid, "path": str(path), "fs": int(fs), "channels": int(x.shape[1]),
        "duration": float(x.shape[0] / fs), "name": pathlib.Path(filename).name[:120],
        "peak": float(np.max(np.abs(x))), "format": ext.lstrip("."),
    }
    AUDIO[aid] = rec
    return rec


def public(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k != "path"}


def envelope(rec: dict, channel: int = 1, points: int = 1500) -> dict:
    x, fs = sf.read(rec["path"], dtype="float32", always_2d=True)
    if channel < 1 or channel > x.shape[1]:
        raise AudioError(f"channel {channel} does not exist")
    y = x[:, channel - 1]
    n = len(y)
    points = max(50, min(points, 6000))
    edges = np.linspace(0, n, points + 1).astype(int)
    mn = [float(y[a:b].min()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]
    mx = [float(y[a:b].max()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]
    t = [float(a / fs) for a in edges[:-1]]
    return {"t": t, "min": mn, "max": mx, "duration": n / fs, "fs": int(fs)}
