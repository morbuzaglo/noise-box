"""Projects and cases: SQLite index + one directory per project (JSON metadata, preserved assets).

Layout (under %LOCALAPPDATA%\\NoiseBox\\projects, overridable with NOISEBOX_DATA):
    noisebox.sqlite
    <project_id>/project.json         metadata (also in the DB)
    <project_id>/assets/<name>.npz    DEM copies (so a case reruns without the original upload)
    <project_id>/assets/<name>.wav    audio copies

A case stores an INPUT SNAPSHOT (the exact request that produced it, with DEM/audio replaced by asset
references), its RESULT, the MATLAB code fingerprint, warnings and execution time. Results are never
recomputed on open: the stored result is shown together with the code version that made it.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any

def base_dir() -> pathlib.Path:
    """Data directory, resolved on every call so NOISEBOX_DATA can be changed (tests, portable installs)."""
    return pathlib.Path(os.environ.get("NOISEBOX_DATA", pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "NoiseBox" / "projects"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '', created REAL, updated REAL, meta TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL, kind TEXT NOT NULL, created REAL, updated REAL,
    input TEXT NOT NULL, result TEXT, status TEXT DEFAULT 'not run', executed REAL,
    fingerprint TEXT, warnings TEXT DEFAULT '[]', validation TEXT DEFAULT 'self-authored tests only; no ISO conformance claimed');
CREATE INDEX IF NOT EXISTS cases_project ON cases(project_id);
"""


class StoreError(ValueError):
    pass


def _db_path() -> pathlib.Path:
    base_dir().mkdir(parents=True, exist_ok=True)
    return base_dir() / "noisebox.sqlite"


@contextmanager
def conn():
    c = sqlite3.connect(str(_db_path()))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _now() -> float:
    return time.time()


def _project_dir(pid: str) -> pathlib.Path:
    d = base_dir() / pid
    (d / "assets").mkdir(parents=True, exist_ok=True)
    return d


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise StoreError("name must be 1-120 characters")
    return name


def _write_meta(pid: str) -> None:
    with conn() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        cases = c.execute("SELECT id,name,kind,status,executed FROM cases WHERE project_id=?", (pid,)).fetchall()
    if row is None:
        return
    meta = {k: row[k] for k in row.keys()}
    meta["meta"] = json.loads(meta["meta"] or "{}")
    meta["cases"] = [dict(r) for r in cases]
    (_project_dir(pid) / "project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ projects
def create_project(name: str, description: str = "", meta: dict | None = None) -> dict:
    pid = uuid.uuid4().hex
    t = _now()
    with conn() as c:
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?)", (pid, _check_name(name), description[:2000], t, t, json.dumps(meta or {})))
    _write_meta(pid)
    return get_project(pid)


def _prow(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in r.keys()}
    d["meta"] = json.loads(d["meta"] or "{}")
    return d


def list_projects() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT p.*, (SELECT COUNT(*) FROM cases WHERE project_id=p.id) AS n_cases FROM projects p ORDER BY updated DESC").fetchall()
    return [_prow(r) for r in rows]


def get_project(pid: str) -> dict:
    with conn() as c:
        r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise KeyError(pid)
    return _prow(r)


def update_project(pid: str, name: str | None = None, description: str | None = None, meta: dict | None = None) -> dict:
    get_project(pid)
    with conn() as c:
        if name is not None:
            c.execute("UPDATE projects SET name=? WHERE id=?", (_check_name(name), pid))
        if description is not None:
            c.execute("UPDATE projects SET description=? WHERE id=?", (description[:2000], pid))
        if meta is not None:
            c.execute("UPDATE projects SET meta=? WHERE id=?", (json.dumps(meta), pid))
        c.execute("UPDATE projects SET updated=? WHERE id=?", (_now(), pid))
    _write_meta(pid)
    return get_project(pid)


def duplicate_project(pid: str, name: str | None = None) -> dict:
    src = get_project(pid)
    new = create_project(name or f"{src['name']} (copy)", src["description"], src["meta"])
    src_assets, dst_assets = _project_dir(pid) / "assets", _project_dir(new["id"]) / "assets"
    for f in src_assets.glob("*"):
        shutil.copy2(f, dst_assets / f.name)
    for cs in list_cases(pid):
        full = get_case(cs["id"])
        add_case(new["id"], full["name"], full["kind"], full["input"], full["result"], full["status"], full["fingerprint"], full["warnings"], full["executed"])
    return get_project(new["id"])


def delete_project(pid: str) -> None:
    get_project(pid)
    with conn() as c:
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    shutil.rmtree(base_dir() / pid, ignore_errors=True)


# --------------------------------------------------------------------- cases
def _crow(r: sqlite3.Row, full: bool) -> dict:
    d = {k: r[k] for k in r.keys()}
    d["warnings"] = json.loads(d["warnings"] or "[]")
    d["fingerprint"] = json.loads(d["fingerprint"]) if d["fingerprint"] else None
    d["input"] = json.loads(d["input"])
    d["result"] = json.loads(d["result"]) if d["result"] else None
    if not full:
        d.pop("input", None)
        d.pop("result", None)
    return d


def add_case(pid: str, name: str, kind: str, inp: dict, result: dict | None = None, status: str = "not run",
             fingerprint: Any = None, warnings: list | None = None, executed: float | None = None) -> dict:
    get_project(pid)
    if kind not in {"point", "section", "terrain"}:
        raise StoreError("kind must be point, section or terrain")
    cid = uuid.uuid4().hex
    t = _now()
    with conn() as c:
        c.execute("INSERT INTO cases (id,project_id,name,kind,created,updated,input,result,status,executed,fingerprint,warnings) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (cid, pid, _check_name(name), kind, t, t, json.dumps(inp), json.dumps(result) if result is not None else None,
                   status, executed, json.dumps(fingerprint) if fingerprint is not None else None, json.dumps(warnings or [])))
        c.execute("UPDATE projects SET updated=? WHERE id=?", (t, pid))
    _write_meta(pid)
    return get_case(cid)


def list_cases(pid: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM cases WHERE project_id=? ORDER BY created", (pid,)).fetchall()
    return [_crow(r, False) for r in rows]


def get_case(cid: str) -> dict:
    with conn() as c:
        r = c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    if r is None:
        raise KeyError(cid)
    return _crow(r, True)


def update_case(cid: str, name: str | None = None, inp: dict | None = None) -> dict:
    old = get_case(cid)
    with conn() as c:
        if name is not None:
            c.execute("UPDATE cases SET name=? WHERE id=?", (_check_name(name), cid))
        if inp is not None:
            # a changed input invalidates the stored result: never show old numbers for new inputs
            c.execute("UPDATE cases SET input=?, result=NULL, status='not run', executed=NULL, fingerprint=NULL, warnings='[]' WHERE id=?", (json.dumps(inp), cid))
        c.execute("UPDATE cases SET updated=? WHERE id=?", (_now(), cid))
        c.execute("UPDATE projects SET updated=? WHERE id=?", (_now(), old["project_id"]))
    _write_meta(old["project_id"])
    return get_case(cid)


def set_result(cid: str, result: dict, fingerprint: Any, warnings: list[str], seconds: float) -> dict:
    case = get_case(cid)
    result = {**result, "seconds": round(seconds, 3)}
    with conn() as c:
        c.execute("UPDATE cases SET result=?, status='completed', executed=?, fingerprint=?, warnings=?, updated=? WHERE id=?",
                  (json.dumps(result), _now(), json.dumps(fingerprint), json.dumps(warnings), _now(), cid))
    _write_meta(case["project_id"])
    return get_case(cid)


def set_failed(cid: str, message: str) -> None:
    with conn() as c:
        c.execute("UPDATE cases SET status=?, updated=? WHERE id=?", (f"failed: {message[:300]}", _now(), cid))


def delete_case(cid: str) -> None:
    case = get_case(cid)
    with conn() as c:
        c.execute("DELETE FROM cases WHERE id=?", (cid,))
    _write_meta(case["project_id"])


def deep_update(base: dict, patch: dict) -> dict:
    """Recursive merge for 'duplicate and change only selected variables'. Lists are replaced, not merged."""
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_update(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def duplicate_case(cid: str, name: str | None = None, overrides: dict | None = None) -> dict:
    src = get_case(cid)
    inp = deep_update(src["input"], overrides or {})
    return add_case(src["project_id"], name or f"{src['name']} (copy)", src["kind"], inp)


# --------------------------------------------------------------------- assets
def save_dem_asset(pid: str, dem: dict, label: str = "dem") -> str:
    import numpy as np

    name = f"{label}-{uuid.uuid4().hex[:8]}.npz"
    meta = {k: dem[k] for k in ("x0", "y0", "cs", "crs", "meta")}
    np.savez_compressed(_project_dir(pid) / "assets" / name, Z=dem["Z"], meta=json.dumps(meta))
    return name


def load_dem_asset(pid: str, name: str) -> dict:
    import numpy as np

    if "/" in name or "\\" in name or not name.endswith(".npz"):
        raise StoreError("bad asset name")
    p = _project_dir(pid) / "assets" / name
    if not p.exists():
        raise StoreError("DEM asset missing")
    z = np.load(p, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    return {**meta, "Z": z["Z"]}


def save_audio_asset(pid: str, src_path: str) -> str:
    name = f"audio-{uuid.uuid4().hex[:8]}.wav"
    shutil.copy2(src_path, _project_dir(pid) / "assets" / name)
    return name
