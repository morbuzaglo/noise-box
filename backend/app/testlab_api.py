"""Test Lab: run the MATLAB test registry (nb_testlab) and export reports.

Every test executes production MATLAB functions (listed per test). Results keep the expected value, the
actual value, the error, the tolerance, the method version and PASS / FAIL / SKIP / BLOCKED / EXTERNAL.
A BLOCKED, SKIP or EXTERNAL test is never counted as passed.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import pathlib
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from . import main as m
from . import store

router = APIRouter(prefix="/api/testlab")
LAST: dict[str, Any] = {"results": [], "started": None, "seconds": None}


def _vec(x) -> list:
    if x is None:
        return []
    if isinstance(x, (int, float)):
        return [x]
    return list(x)


def _clean(r: dict) -> dict:
    keep = ("id", "group", "title", "source", "calls", "status", "detail")
    out = {k: r.get(k) for k in keep}
    out["calls"] = [c for c in _vec(r.get("calls"))] if r.get("calls") else []
    lab = r.get("labels")
    out["labels"] = [lab] if isinstance(lab, str) else _vec(lab)
    for k in ("expected", "actual", "err", "tol"):
        out[k] = _vec(r.get(k))
    out["pass"] = [bool(v) for v in _vec(r.get("pass"))]
    errs = [abs(e) for e in out["err"] if e is not None]
    out["max_abs_error"] = max(errs) if errs else None
    out["n"] = len(out["expected"])
    out["n_pass"] = sum(out["pass"])
    return out


def _worker():
    w = m.state["worker"]
    try:
        w.wait_ready(timeout=0.01)
    except TimeoutError:
        raise HTTPException(503, "MATLAB Engine is still starting")
    return w


@router.get("/catalog")
def catalog():
    return _catalog(_worker())


def _catalog(w):
    raw = w.run_call("nb_testlab", ["catalog"])
    ids = _vec(raw["id"])
    rows = []
    for i, tid in enumerate(ids):
        calls = raw["calls"][i] if isinstance(raw["calls"], list) else raw["calls"]
        rows.append({"id": tid, "group": raw["group"][i], "title": raw["title"][i], "source": raw["source"][i],
                     "calls": calls if isinstance(calls, list) else ([calls] if calls else []), "status0": raw["status0"][i]})
    return rows


class RunIn(BaseModel):
    ids: list[str] | None = None
    group: str | None = None       # prefix such as "G3"


@router.post("/run")
def run(req: RunIn):
    w = _worker()
    cat = _catalog(w)
    ids = [r["id"] for r in cat if (not req.ids or r["id"] in req.ids) and (not req.group or r["id"].startswith(req.group))]
    if not ids:
        raise HTTPException(422, "no matching tests")
    t0 = time.time()
    results = []
    for tid in ids:
        raw = w.run_call("nb_testlab", ["run", tid])
        results.append(_clean(m._json_safe(raw)))
    LAST.update(results=results, started=t0, seconds=round(time.time() - t0, 2), meta=_meta(w))
    _write_log()
    return summary()


def _meta(w) -> dict:
    fp = w.dependency_fingerprint("nb_testlab")
    return {"matlab_release": "R2023a (9.14)", "code_sha256": fp, "software": "noise-box 0.1",
            "standards": {"published": "ISO 9613-2:2024", "draft": "DAmd 1 eqs. 18/21 (DRAFT)", "benchmarks": "ISO/TR 17534-3:2015 against ISO 9613-2:1996 compatibility mode"}}


def summary() -> dict:
    res = LAST["results"]
    counts: dict[str, int] = {}
    for r in res:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"results": res, "counts": counts, "seconds": LAST.get("seconds"), "started": LAST.get("started"), "meta": LAST.get("meta")}


@router.get("/last")
def last():
    return summary()


def _write_log() -> None:
    d = store.base_dir() / "testlab"
    d.mkdir(parents=True, exist_ok=True)
    (d / "last_run.json").write_text(json.dumps(summary(), indent=1), encoding="utf-8")


@router.get("/report.json")
def report_json():
    if not LAST["results"]:
        raise HTTPException(409, "run the tests first")
    return Response(json.dumps(summary(), indent=1), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="testlab-log.json"'})


@router.get("/report.md")
def report_md():
    if not LAST["results"]:
        raise HTTPException(409, "run the tests first")
    s = summary()
    when = dt.datetime.fromtimestamp(s["started"], dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if s["started"] else ""
    lines = [f"# Noise Box test report", "", f"Run: {when}, {s['seconds']} s. MATLAB {s['meta']['matlab_release']}.", "",
             "Counts: " + ", ".join(f"{k} {v}" for k, v in sorted(s["counts"].items())), "",
             "Passing these tests is not an ISO certification. G3 compares against reference values that target ISO 9613-2:1996 "
             "using an explicitly labelled compatibility mode; BLOCKED, SKIP and EXTERNAL tests are not passes.", ""]
    group = None
    for r in s["results"]:
        if r["group"] != group:
            group = r["group"]
            lines += ["", f"## {group}", "", "| Test | Status | Rows pass | Max abs error | Source |", "|---|---|---|---|---|"]
        mx = "" if r["max_abs_error"] is None else f"{r['max_abs_error']:.4f}"
        lines.append(f"| {r['id']} {r['title']} | {r['status']} | {r['n_pass']}/{r['n']} | {mx} | {r['source']} |")
        if r["status"] in ("BLOCKED", "SKIP", "EXTERNAL") and r.get("detail"):
            lines.append(f"|  | {r['detail']} | | | |")
    return Response("\n".join(lines), media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="testlab-report.md"'})


def _scene(test_id: str):
    if not test_id.startswith("G3-T"):
        raise HTTPException(422, "only ISO/TR 17534-3 test scenes have a geometry")
    w = _worker()
    sc = m._json_safe(w.run_call("nb_bench_scene", [test_id[3:]]))
    if not sc.get("loadable"):
        raise HTTPException(422, f"no scene geometry for this test: {sc.get('reason')}")

    def vec(v):
        return [v] if isinstance(v, (int, float)) else list(v)

    def seq(v):
        return v if isinstance(v, list) else ([v] if v else [])

    obstacles = [{"x": vec(o["x"]), "y": vec(o["y"]), "top": o["top"]} for o in seq(sc.get("obstacles"))]
    areas = [{"x": vec(a["x"]), "y": vec(a["y"]), "G": a["G"]} for a in seq(sc.get("areas"))]
    return sc, vec(sc["S"]), vec(sc["R"]), obstacles, areas


@router.get("/{test_id}/scene")
def scene(test_id: str):
    sc, S, R, obstacles, areas = _scene(test_id)
    return {"id": test_id, "title": sc["title"], "S": S, "R": R, "obstacles": obstacles, "areas": areas, "G": sc["G"], "G0": sc["G0"], "mode": sc["mode"]}


class LoadIn(BaseModel):
    project_id: str


@router.post("/{test_id}/load")
def load_as_case(test_id: str, body: LoadIn):
    """Create an editable terrain case from an ISO/TR 17534-3 scene (flat DEM + obstacles + ground areas)."""
    if not test_id.startswith("G3-T"):
        raise HTTPException(422, "only ISO/TR 17534-3 test scenes can be loaded")
    w = _worker()
    try:
        store.get_project(body.project_id)
    except KeyError:
        raise HTTPException(404, "unknown project")
    sc = m._json_safe(w.run_call("nb_bench_scene", [test_id[3:]]))
    if not sc.get("loadable"):
        raise HTTPException(422, f"this test cannot be loaded as a scene: {sc.get('reason')}")
    from . import dem as dem_io


    def lst(v):
        return v if isinstance(v, list) else [v]

    def vec(v):
        return [v] if isinstance(v, (int, float)) else list(v)

    obstacles = []
    for o in (sc.get("obstacles") if isinstance(sc.get("obstacles"), list) else [sc.get("obstacles")] if sc.get("obstacles") else []):
        x, y = vec(o["x"]), vec(o["y"])
        obstacles.append({"kind": "wall" if len(x) == 2 else "building", "x": x, "y": y, "h": o["top"]})
    areas = []
    for a in (sc.get("areas") if isinstance(sc.get("areas"), list) else [sc.get("areas")] if sc.get("areas") else []):
        areas.append({"x": vec(a["x"]), "y": vec(a["y"]), "G": a["G"]})
    S, R = vec(sc["S"]), vec(sc["R"])
    xs_all = [S[0], R[0]] + [v for o in obstacles for v in o["x"]] + [v for a in areas for v in a["x"]]
    ys_all = [S[1], R[1]] + [v for o in obstacles for v in o["y"]] + [v for a in areas for v in a["y"]]
    cs, pad = 10.0, 30.0
    x0, y0 = math.floor((min(xs_all) - pad) / cs) * cs, math.floor((min(ys_all) - pad) / cs) * cs
    nx, ny = int(math.ceil((max(xs_all) + pad - x0) / cs)) + 1, int(math.ceil((max(ys_all) + pad - y0) / cs)) + 1
    dem = dem_io.synthetic("flat", nx, ny, cs, x0, y0)
    did = f"bench:{test_id}"
    m.DEMS[did] = dem
    G = sc["G0"] if areas else sc["G"]
    atm = sc["atm"]
    request = {
        "Lw": vec(sc["Lw"]), "G": {"Gs": G, "Gm": G, "Gr": G}, "atm": {"T_C": atm["T_C"], "RH": atm["RH"], "p_kPa": atm["p_kPa"]},
        "mode": "iso1996", "source": {"x": S[0], "y": S[1], "h": S[2]}, "hr": R[2],
        "grid": {"x0": x0, "x1": x0 + cs * (nx - 1), "nx": 40, "y0": y0, "y1": y0 + cs * (ny - 1), "ny": 40},
        "obstacles": obstacles, "ground_areas": areas, "ground_default": sc["G0"] if areas else None,
        "ground_method": sc.get("groundMethod", "general"),
    }
    inp = {"request": {**request, "dem_id": did}, "receivers": [{"name": test_id[3:], "x": R[0], "y": R[1], "h": R[2]}], "run_field": True}
    from . import projects_api as pa

    pa._validate("terrain", inp)
    inp = pa._persist_assets(body.project_id, "terrain", inp)
    case = store.add_case(body.project_id, f"{test_id[3:]} {sc['title']}"[:120], "terrain", inp)
    return case
