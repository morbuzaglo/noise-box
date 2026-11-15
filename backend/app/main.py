"""Local API for the acoustic simulator. Binds to localhost only (see run_server.py).

The API never executes browser-supplied MATLAB code. /api/run accepts a
validated case description and calls the allow-listed entry point
`run_acoustic_case` in the configured MATLAB library folder.
"""
from __future__ import annotations

import os
import pathlib
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from . import audio as audio_io
from . import dem as dem_io
from .matlab_worker import MatlabWorker

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIBRARY = pathlib.Path(os.environ.get("NOISEBOX_MATLAB_LIB", ROOT / "matlab" / "core"))
ENTRY = "run_acoustic_case"

state: dict[str, MatlabWorker] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    w = MatlabWorker(LIBRARY)
    state["worker"] = w
    yield
    w.close()


app = FastAPI(title="noise-box", version="0.1.0", lifespan=lifespan)


class Ground(BaseModel):
    Gs: float = Field(ge=0, le=1)
    Gm: float = Field(ge=0, le=1)
    Gr: float = Field(ge=0, le=1)


class Atmosphere(BaseModel):
    T_C: float = Field(ge=-40, le=60)
    RH: float = Field(gt=0, le=100)
    p_kPa: float = Field(gt=50, lt=120)


class PathGeom(BaseModel):
    z: float
    dss: float = Field(gt=0)
    dsr: float = Field(gt=0)
    e: float = Field(ge=0)


class Barrier(PathGeom):
    side1: PathGeom | None = None
    side2: PathGeom | None = None


class Limits(BaseModel):
    # None entries mean "no limit for that band" and are sent to MATLAB as NaN.
    bands: list[float | None] | None = None
    weighting: Literal["Z", "A"] = "Z"
    overallA: float | None = None

    @field_validator("bands")
    @classmethod
    def eight(cls, v):
        if v is not None and len(v) != 8:
            raise ValueError("limits.bands needs exactly 8 entries (null = no limit)")
        return v


class CaseIn(BaseModel):
    Lw: list[float]
    Dc: list[float] | None = None
    hs: float = Field(ge=0)
    hr: float = Field(ge=0)
    dp: float = Field(gt=0)
    dh: float = 0.0
    G: Ground
    atm: Atmosphere
    mode: Literal["iso2024", "draft2026", "iso1996"] = "iso2024"
    barrier: Barrier | None = None
    C0: float | None = Field(default=None, ge=0)
    limits: Limits | None = None
    enclosure: "Enclosure | None" = None

    @field_validator("Lw", "Dc")
    @classmethod
    def eight_bands(cls, v):
        if v is not None and len(v) != 8:
            raise ValueError("expected exactly 8 octave-band values (63..8000 Hz)")
        return v


class Terrain2D(BaseModel):
    x: list[float] = Field(min_length=2)
    z: list[float] = Field(min_length=2)

    @field_validator("z")
    @classmethod
    def same_len(cls, v, info):
        if "x" in info.data and len(v) != len(info.data["x"]):
            raise ValueError("terrain x and z must have equal length")
        return v


class GridSpec(BaseModel):
    x0: float
    x1: float
    nx: int = Field(ge=2, le=400)
    z0: float
    z1: float
    nz: int = Field(ge=2, le=400)


class Field2DIn(BaseModel):
    Lw: list[float]
    G: Ground
    atm: Atmosphere
    mode: Literal["iso2024", "draft2026", "iso1996"] = "iso2024"
    terrain: Terrain2D
    source_x: float
    source_h: float = Field(ge=0)
    grid: GridSpec
    limits: Limits | None = None
    enclosure: "Enclosure | None" = None

    @field_validator("Lw")
    @classmethod
    def eight(cls, v):
        if len(v) != 8:
            raise ValueError("expected exactly 8 octave-band values")
        return v


MAX_POINTS = 40_000


@app.post("/api/field2d")
def field2d(req: Field2DIn, use_cache: bool = True):
    w = state["worker"]
    try:
        w.wait_ready(timeout=0.01)
    except TimeoutError:
        raise HTTPException(503, "MATLAB Engine is still starting")
    g = req.grid
    if g.nx * g.nz > MAX_POINTS:
        raise HTTPException(422, f"grid too large: {g.nx * g.nz} points (max {MAX_POINTS})")
    xs = [g.x0 + (g.x1 - g.x0) * i / (g.nx - 1) for i in range(g.nx)]
    zs = [g.z0 + (g.z1 - g.z0) * j / (g.nz - 1) for j in range(g.nz)]
    payload = {
        "Lw": req.Lw, "G": req.G.model_dump(), "atm": req.atm.model_dump(), "mode": req.mode,
        "terrain": req.terrain.model_dump(),
        "source": {"x": req.source_x, "h": req.source_h},
        "grid": {"x": xs, "z": zs},
    }
    if req.enclosure is not None:
        payload["enclosure"] = _enclosure(req.enclosure)
    if req.limits is not None:
        lim = req.limits.model_dump()
        lim["bands"] = [float("nan") if b is None else b for b in (lim["bands"] or [None] * 8)]
        lim["overallA"] = float("nan") if lim["overallA"] is None else lim["overallA"]
        payload["limits"] = lim
    try:
        res = w.run("run_field_2d", payload, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"MATLAB error: {exc}")
    return _json_safe(res)


UPLOAD_DIR = pathlib.Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "NoiseBox" / "uploads"
MAX_UPLOAD = 150 * 1024 * 1024
DEMS: dict[str, dict] = {}


@app.post("/api/dem/upload")
async def dem_upload(
    file: UploadFile = File(...),
    vertical_unit: str = Form(...),
    declared_metric: bool = Form(False),
):
    """Import ESRI ASCII (.asc), regular-grid XYZ/CSV, or GeoTIFF. Client file names are never used as paths."""
    ext = pathlib.Path(file.filename or "").suffix.lower()
    if ext not in {".asc", ".txt", ".csv", ".xyz", ".tif", ".tiff"}:
        raise HTTPException(415, "unsupported file type (allowed: .asc .txt .csv .xyz .tif .tiff)")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    name = pathlib.Path(file.filename or "upload").name[:120]
    try:
        if ext in {".tif", ".tiff"}:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            tmp = UPLOAD_DIR / f"{uuid.uuid4().hex}.tif"
            tmp.write_bytes(data)
            try:
                dem = dem_io.load_geotiff(tmp, vertical_unit, name)
            finally:
                tmp.unlink(missing_ok=True)
        elif ext == ".asc":
            dem = dem_io.load_esri_ascii(data, vertical_unit, declared_metric, name)
        else:
            dem = dem_io.load_xyz(data, vertical_unit, declared_metric, name)
    except dem_io.DemError as exc:
        raise HTTPException(422, str(exc))
    did = uuid.uuid4().hex
    DEMS[did] = dem
    return {"dem_id": did, **_dem_summary(dem)}


class SyntheticIn(BaseModel):
    kind: Literal["flat", "ridge", "hill"]
    nx: int = Field(default=61, ge=5, le=400)
    ny: int = Field(default=61, ge=5, le=400)
    cs: float = Field(default=5.0, gt=0, le=100)
    x0: float = 0.0
    y0: float = 0.0


@app.post("/api/dem/synthetic")
def dem_synthetic(req: SyntheticIn):
    dem = dem_io.synthetic(req.kind, req.nx, req.ny, req.cs, req.x0, req.y0)
    did = uuid.uuid4().hex
    DEMS[did] = dem
    return {"dem_id": did, **_dem_summary(dem)}


def _dem_summary(dem: dict) -> dict:
    Z = dem["Z"]
    import numpy as np

    return {
        "x0": dem["x0"], "y0": dem["y0"], "cs": dem["cs"], "nx": int(Z.shape[1]), "ny": int(Z.shape[0]),
        "crs": dem["crs"], "meta": dem["meta"],
        "zmin": float(np.nanmin(Z)), "zmax": float(np.nanmax(Z)), "nan_cells": int(np.isnan(Z).sum()),
    }


@app.get("/api/dem/{dem_id}")
def dem_get(dem_id: str, stride: int = 1):
    dem = DEMS.get(dem_id)
    if dem is None:
        raise HTTPException(404, "unknown DEM")
    stride = max(1, min(stride, 50))
    d = {**dem, "Z": dem["Z"][::stride, ::stride]}
    d["cs"] = dem["cs"] * stride
    return {**dem_io.to_payload(d), "stride": stride}


class Source3D(BaseModel):
    x: float
    y: float
    h: float = Field(ge=0)


class Grid3D(BaseModel):
    x0: float
    x1: float
    nx: int = Field(ge=2, le=300)
    y0: float
    y1: float
    ny: int = Field(ge=2, le=300)


class Material(BaseModel):
    """Transmission data. Give measured TL (preferred) or a surface mass (rough mass-law estimate).
    volume_density x thickness is accepted only with solid=True (homogeneous solid layer)."""
    surface_mass: float | None = Field(default=None, gt=0, le=1e5)     # kg/m^2
    volume_density: float | None = Field(default=None, gt=0, le=2e4)   # kg/m^3, NOT a surface mass
    thickness: float | None = Field(default=None, gt=0, le=10)         # m
    solid: bool = False
    TL: list[float] | None = None                                      # 8 octave bands, dB
    openness: float = Field(default=0.0, ge=0, le=1)                   # open area fraction
    tl_model: Literal["normal", "field"] = "normal"

    @field_validator("TL")
    @classmethod
    def tl8(cls, v):
        if v is not None and (len(v) != 8 or any(t < 0 for t in v)):
            raise ValueError("TL needs 8 non-negative octave-band values (63..8000 Hz)")
        return v

    @model_validator(mode="after")
    def has_basis(self):
        if self.TL is None and self.surface_mass is None and (self.volume_density is None or self.thickness is None):
            raise ValueError("give measured TL, a surface mass, or volume density + thickness (solid layer)")
        return self


class Enclosure(BaseModel):
    S_total: float = Field(gt=0, le=1e5)      # enclosure surface area, m^2
    A_in: float = Field(gt=0, le=1e5)         # equivalent absorption area inside, m^2
    S_open: float = Field(default=0.0, ge=0)  # openings, m^2
    material: Material

    @model_validator(mode="after")
    def open_ok(self):
        if self.S_open > self.S_total:
            raise ValueError("S_open cannot exceed S_total")
        return self


def _enclosure(e: "Enclosure | None") -> dict | None:
    if e is None:
        return None
    return {"S_total": e.S_total, "A_in": e.A_in, "S_open": e.S_open, "mat": e.material.model_dump(exclude_none=True)}


class Obstacle(BaseModel):
    """Wall (2 vertices, thin, one diffracting edge) or building footprint (>= 3 vertices)."""
    kind: Literal["wall", "building"]
    x: list[float] = Field(min_length=2, max_length=64)
    y: list[float] = Field(min_length=2, max_length=64)
    h: float = Field(gt=0, le=500)        # height of the flat top above the highest ground under it
    name: str = Field(default="", max_length=80)
    gap: float = Field(default=0.0, ge=0, le=100)     # bottom clearance of a hanging screen, m
    material: Material | None = None                  # present = sound also transmits through it

    @field_validator("y")
    @classmethod
    def same_len(cls, v, info):
        x = info.data.get("x")
        if x is not None and len(v) != len(x):
            raise ValueError("x and y must have equal length")
        kind = info.data.get("kind")
        if kind == "wall" and len(v) != 2:
            raise ValueError("a wall has exactly 2 vertices (centre line)")
        if kind == "building" and len(v) < 3:
            raise ValueError("a building footprint needs at least 3 vertices")
        return v


def _ground_extras(req) -> dict:
    d: dict = {}
    if getattr(req, "ground_areas", None):
        d["groundAreas"] = [{"x": a.x, "y": a.y, "G": a.G} for a in req.ground_areas]
    if getattr(req, "ground_default", None) is not None:
        d["Gdefault"] = req.ground_default
    if getattr(req, "ground_method", "general") != "general":
        d["groundMethod"] = req.ground_method
    return d


def _obstacles(items: list["Obstacle"]) -> list[dict]:
    out = []
    for o in items:
        d: dict = {"x": o.x, "y": o.y, "h": o.h}
        if o.gap > 0:
            d["gap"] = o.gap
        if o.material is not None:
            d["mat"] = o.material.model_dump(exclude_none=True)
        out.append(d)
    return out


class GroundArea(BaseModel):
    """Plan polygon with its own ground factor G (areas must not overlap)."""
    x: list[float] = Field(min_length=3, max_length=64)
    y: list[float] = Field(min_length=3, max_length=64)
    G: float = Field(ge=0, le=1)

    @field_validator("y")
    @classmethod
    def same_len(cls, v, info):
        if "x" in info.data and len(v) != len(info.data["x"]):
            raise ValueError("x and y must have equal length")
        return v


class Receiver3D(BaseModel):
    x: float
    y: float
    h: float = Field(default=1.5, ge=0)


class Case3DIn(BaseModel):
    dem_id: str
    Lw: list[float]
    G: Ground
    atm: Atmosphere
    mode: Literal["iso2024", "draft2026", "iso1996"] = "iso2024"
    source: Source3D
    receiver: Receiver3D
    obstacles: list[Obstacle] = []
    limits: Limits | None = None
    enclosure: Enclosure | None = None
    ground_areas: list[GroundArea] = []
    ground_default: float | None = Field(default=None, ge=0, le=1)
    ground_method: Literal["general", "simplified"] = "general"

    @field_validator("Lw")
    @classmethod
    def eight(cls, v):
        if len(v) != 8:
            raise ValueError("expected exactly 8 octave-band values")
        return v


@app.post("/api/case3d")
def case3d(req: Case3DIn, use_cache: bool = True):
    """One receiver with full path geometry (top and lateral paths, flags) for inspection."""
    w = state["worker"]
    try:
        w.wait_ready(timeout=0.01)
    except TimeoutError:
        raise HTTPException(503, "MATLAB Engine is still starting")
    dem = DEMS.get(req.dem_id)
    if dem is None:
        raise HTTPException(404, "unknown DEM (upload it again)")
    payload = {
        "Lw": req.Lw, "G": req.G.model_dump(), "atm": req.atm.model_dump(), "mode": req.mode,
        "dem": dem_io.to_matlab(dem), "source": req.source.model_dump(), "receiver": req.receiver.model_dump(),
        "obstacles": _obstacles(req.obstacles),
        **_ground_extras(req),
    }
    if req.enclosure is not None:
        payload["enclosure"] = _enclosure(req.enclosure)
    if req.limits is not None:
        lim = req.limits.model_dump()
        lim["bands"] = [float("nan") if b is None else b for b in (lim["bands"] or [None] * 8)]
        lim["overallA"] = float("nan") if lim["overallA"] is None else lim["overallA"]
        payload["limits"] = lim
    try:
        res = w.run("run_case_3d", payload, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"MATLAB error: {exc}")
    return _json_safe(res)


class Field3DIn(BaseModel):
    dem_id: str
    Lw: list[float]
    G: Ground
    atm: Atmosphere
    mode: Literal["iso2024", "draft2026", "iso1996"] = "iso2024"
    source: Source3D
    grid: Grid3D
    hr: float = Field(default=1.5, ge=0)
    obstacles: list[Obstacle] = []
    limits: Limits | None = None
    enclosure: Enclosure | None = None
    ground_areas: list[GroundArea] = []
    ground_default: float | None = Field(default=None, ge=0, le=1)
    ground_method: Literal["general", "simplified"] = "general"

    @field_validator("Lw")
    @classmethod
    def eight(cls, v):
        if len(v) != 8:
            raise ValueError("expected exactly 8 octave-band values")
        return v


@app.post("/api/field3d")
def field3d(req: Field3DIn, use_cache: bool = True):
    w = state["worker"]
    try:
        w.wait_ready(timeout=0.01)
    except TimeoutError:
        raise HTTPException(503, "MATLAB Engine is still starting")
    dem = DEMS.get(req.dem_id)
    if dem is None:
        raise HTTPException(404, "unknown DEM (upload it again)")
    g = req.grid
    if g.nx * g.ny > MAX_POINTS:
        raise HTTPException(422, f"grid too large: {g.nx * g.ny} points (max {MAX_POINTS})")
    xs = [g.x0 + (g.x1 - g.x0) * i / (g.nx - 1) for i in range(g.nx)]
    ys = [g.y0 + (g.y1 - g.y0) * j / (g.ny - 1) for j in range(g.ny)]
    payload = {
        "Lw": req.Lw, "G": req.G.model_dump(), "atm": req.atm.model_dump(), "mode": req.mode,
        "dem": dem_io.to_matlab(dem), "source": req.source.model_dump(), "grid": {"x": xs, "y": ys}, "hr": req.hr,
        "obstacles": _obstacles(req.obstacles),
        **_ground_extras(req),
    }
    if req.enclosure is not None:
        payload["enclosure"] = _enclosure(req.enclosure)
    if req.limits is not None:
        lim = req.limits.model_dump()
        lim["bands"] = [float("nan") if b is None else b for b in (lim["bands"] or [None] * 8)]
        lim["overallA"] = float("nan") if lim["overallA"] is None else lim["overallA"]
        payload["limits"] = lim
    try:
        res = w.run("run_field_3d", payload, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"MATLAB error: {exc}")
    return _json_safe(res)


@app.post("/api/audio/upload")
async def audio_upload(file: UploadFile = File(...)):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    try:
        return audio_io.public(audio_io.store(data, file.filename or ""))
    except audio_io.AudioError as exc:
        raise HTTPException(422, str(exc))


def _audio(aid: str) -> dict:
    rec = audio_io.AUDIO.get(aid)
    if rec is None:
        raise HTTPException(404, "unknown audio (upload it again)")
    return rec


@app.get("/api/audio/{audio_id}/waveform")
def audio_waveform(audio_id: str, channel: int = 1, points: int = 1500):
    try:
        return audio_io.envelope(_audio(audio_id), channel, points)
    except audio_io.AudioError as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/audio/{audio_id}/file")
def audio_file(audio_id: str):
    rec = _audio(audio_id)
    return FileResponse(rec["path"], media_type="audio/wav", filename="recording.wav")


class Interval(BaseModel):
    audio_id: str
    start: float = Field(ge=0)
    stop: float = Field(gt=0)
    channel: int = Field(default=1, ge=1, le=64)

    @model_validator(mode="after")
    def ordered(self):
        if self.stop - self.start < 0.1:
            raise ValueError("interval must be at least 0.1 s")
        if self.stop - self.start > 600:
            raise ValueError("interval longer than 600 s; select a shorter segment")
        return self


class CalibratorIn(Interval):
    level: float = Field(ge=60, le=160)       # dB re 20 uPa
    freq: float = Field(default=1000.0, ge=50, le=8000)


class Calibration(BaseModel):
    mode: Literal["none", "sensitivity", "calibrator"] = "none"
    pa_per_unit: float | None = Field(default=None, gt=0)
    calibrator: CalibratorIn | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.mode == "sensitivity" and self.pa_per_unit is None:
            raise ValueError("sensitivity mode needs pa_per_unit")
        if self.mode == "calibrator" and self.calibrator is None:
            raise ValueError("calibrator mode needs a calibrator recording")
        return self


class MicGeometry(BaseModel):
    hs: float = Field(ge=0)
    hm: float = Field(ge=0)
    dp: float = Field(gt=0)
    dh: float = 0.0
    G: Ground
    atm: Atmosphere
    Dc: list[float] | None = None
    srcDim: float | None = Field(default=None, gt=0)

    @field_validator("Dc")
    @classmethod
    def eight(cls, v):
        if v is not None and len(v) != 8:
            raise ValueError("Dc needs 8 values")
        return v


class AudioAnalysisIn(BaseModel):
    signal: Interval
    calibration: Calibration = Calibration()
    background: Interval | None = None
    estimate: MicGeometry | None = None


@app.post("/api/audio/analyze")
def audio_analyze(req: AudioAnalysisIn, use_cache: bool = True):
    w = state["worker"]
    try:
        w.wait_ready(timeout=0.01)
    except TimeoutError:
        raise HTTPException(503, "MATLAB Engine is still starting")
    s = req.signal
    rec = _audio(s.audio_id)
    if s.stop > rec["duration"] + 1e-6 or s.channel > rec["channels"]:
        raise HTTPException(422, "interval or channel outside the recording")
    payload: dict = {"file": rec["path"], "channel": s.channel, "start": s.start, "stop": s.stop}
    cal = req.calibration
    if cal.mode == "sensitivity":
        payload["paPerUnit"] = cal.pa_per_unit
    elif cal.mode == "calibrator":
        c = cal.calibrator
        crec = _audio(c.audio_id)
        if c.stop > crec["duration"] + 1e-6:
            raise HTTPException(422, "calibrator interval outside its recording")
        if crec["fs"] != rec["fs"]:
            raise HTTPException(422, "calibrator and signal recordings need the same sample rate")
        payload["calibrator"] = {"file": crec["path"], "start": c.start, "stop": c.stop, "level": c.level, "freq": c.freq}
    if req.background is not None:
        b = req.background
        brec = _audio(b.audio_id)
        if b.stop > brec["duration"] + 1e-6:
            raise HTTPException(422, "background interval outside its recording")
        if brec["fs"] != rec["fs"]:
            raise HTTPException(422, "background and signal recordings need the same sample rate")
        payload["background"] = {"file": brec["path"], "channel": b.channel, "start": b.start, "stop": b.stop}
    if req.estimate is not None:
        e = req.estimate
        est = {"g": {"hs": e.hs, "hm": e.hm, "dp": e.dp, "dh": e.dh}, "G": e.G.model_dump(), "atm": e.atm.model_dump()}
        if e.Dc is not None:
            est["Dc"] = e.Dc
        if e.srcDim is not None:
            est["srcDim"] = e.srcDim
        payload["estimate"] = est
    try:
        res = w.run("run_audio_analysis", payload, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        raise HTTPException(422, msg.split("Error:", 1)[-1].strip() if "No calibration" in msg else f"MATLAB error: {msg}")
    return _json_safe(res)


@app.get("/api/health")
def health():
    w = state["worker"]
    try:
        w.wait_ready(timeout=0.01)
        matlab = "ready"
    except TimeoutError:
        matlab = "starting"
    except RuntimeError as exc:
        matlab = f"error: {exc}"
    return {"matlab": matlab, "library": str(w.library_dir), "stats": w.stats}


@app.get("/api/functions")
def functions():
    """Function registry. verification = number of Test Lab tests that call the function (0 = untested here)."""
    rows = state["worker"].functions()
    try:
        from .testlab_api import _catalog

        cat = _catalog(state["worker"])
        for r in rows:
            r["linked_tests"] = sorted(t["id"] for t in cat if r["name"] in (t["calls"] or []))
    except Exception:  # noqa: BLE001
        for r in rows:
            r.setdefault("linked_tests", [])
    return rows


@app.post("/api/matlab/refresh")
def matlab_refresh():
    return state["worker"].refresh()


class WatchIn(BaseModel):
    on: bool


@app.post("/api/matlab/watch")
def matlab_watch(body: WatchIn):
    w = state["worker"]
    w.start_watch() if body.on else w.stop_watch()
    return {"watching": w.watching}


@app.get("/api/diagnostics")
def diagnostics():
    import platform
    import sys

    w = state["worker"]
    info: dict = {"python": sys.version.split()[0], "platform": platform.platform(), "library": str(w.library_dir), "watching": w.watching,
                  "engine_requirement": "MATLAB R2023a supports Python 3.8-3.10 for the Engine API; MATLAB Runtime alone is not sufficient."}
    try:
        w.wait_ready(timeout=0.01)
        info["matlab"] = _json_safe(w.run_call("nb_diagnostics", []))
        info["state"] = "ready"
    except TimeoutError:
        info["state"] = "starting"
    except Exception as exc:  # noqa: BLE001
        info["state"] = f"error: {exc}"
    return info


@app.post("/api/run")
def run(case: CaseIn, use_cache: bool = True):
    w = state["worker"]
    try:
        w.wait_ready(timeout=0.01)
    except TimeoutError:
        raise HTTPException(503, "MATLAB Engine is still starting")
    payload = case.model_dump(exclude_none=True)
    if case.enclosure is not None:
        payload["enclosure"] = _enclosure(case.enclosure)
    if case.limits is not None and case.limits.bands is not None:
        # exclude_none dropped the None entries inside the list only if filtered; rebuild with NaN.
        payload["limits"]["bands"] = [float("nan") if b is None else b for b in case.limits.bands]
    try:
        return _json_safe(w.run(ENTRY, payload, use_cache=use_cache))
    except Exception as exc:  # noqa: BLE001  MATLAB errors are returned, not hidden
        raise HTTPException(422, f"MATLAB error: {exc}")


def _json_safe(x):
    """NaN/Inf are not valid JSON: send null (meaning 'no value'), never a fake number."""
    import math

    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    return x


from .projects_api import router as _projects_router  # noqa: E402

app.include_router(_projects_router)

from .testlab_api import router as _testlab_router  # noqa: E402

app.include_router(_testlab_router)
