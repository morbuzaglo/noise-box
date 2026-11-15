"""Projects, cases, comparison and export endpoints.

A case input is a snapshot:
    point   {"request": <CaseIn>, "receivers": [{"name"}]}
    section {"request": <Field2DIn>, "receivers": [{"name","x","h"}], "run_field": true}
    terrain {"request": <Field3DIn without dem_id>, "dem_asset": "...", "dem_info": {...},
             "receivers": [{"name","x","y","h"}], "run_field": true}
Running a case calls the same MATLAB entry points as the live endpoints and stores the normalised result
together with the MATLAB code fingerprint. Editing a case's input clears its stored result.
"""
from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from . import export_xlsx, store
from . import main as m

router = APIRouter(prefix="/api")


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["point", "section", "terrain"]
    input: dict


class CasePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    input: dict | None = None


class DuplicateIn(BaseModel):
    name: str | None = None
    overrides: dict = {}


def _nf(fn, *a):
    try:
        return fn(*a)
    except KeyError:
        raise HTTPException(404, "not found")
    except store.StoreError as exc:
        raise HTTPException(422, str(exc))


# ------------------------------------------------------------------ validation
def _validate(kind: str, inp: dict) -> None:
    req = inp.get("request")
    if not isinstance(req, dict):
        raise HTTPException(422, "input.request is required")
    try:
        if kind == "point":
            m.CaseIn(**req)
        elif kind == "section":
            m.Field2DIn(**req)
        else:
            m.Field3DIn(**{**req, "dem_id": "placeholder"})
    except Exception as exc:  # noqa: BLE001  pydantic validation error text is user-facing
        raise HTTPException(422, f"invalid {kind} request: {exc}")
    for rcv in inp.get("receivers", []):
        if not str(rcv.get("name", "")).strip():
            raise HTTPException(422, "every receiver needs a name")


def _persist_assets(pid: str, kind: str, inp: dict) -> dict:
    inp = dict(inp)
    if kind == "terrain":
        req = dict(inp["request"])
        did = req.pop("dem_id", None)
        if did:
            dem = m.DEMS.get(did)
            if dem is None:
                raise HTTPException(404, "unknown DEM (upload it again)")
            inp["dem_asset"] = store.save_dem_asset(pid, dem)
            inp["dem_info"] = m._dem_summary(dem)
        if "dem_asset" not in inp:
            raise HTTPException(422, "a terrain case needs a DEM")
        inp["request"] = req
    return inp


# -------------------------------------------------------------------- projects
@router.get("/projects")
def projects():
    return store.list_projects()


@router.post("/projects")
def project_create(p: ProjectIn):
    return store.create_project(p.name, p.description)


@router.get("/projects/{pid}")
def project_get(pid: str):
    proj = _nf(store.get_project, pid)
    return {**proj, "cases": store.list_cases(pid)}


@router.patch("/projects/{pid}")
def project_patch(pid: str, p: ProjectPatch):
    return _nf(store.update_project, pid, p.name, p.description)


@router.post("/projects/{pid}/duplicate")
def project_duplicate(pid: str, d: DuplicateIn):
    return _nf(store.duplicate_project, pid, d.name)


@router.delete("/projects/{pid}")
def project_delete(pid: str):
    _nf(store.delete_project, pid)
    return {"deleted": pid}


# ----------------------------------------------------------------------- cases
@router.post("/projects/{pid}/cases")
def case_create(pid: str, c: CaseCreate):
    _nf(store.get_project, pid)
    _validate(c.kind, c.input)
    inp = _persist_assets(pid, c.kind, c.input)
    return _nf(store.add_case, pid, c.name, c.kind, inp)


@router.get("/cases/{cid}")
def case_get(cid: str):
    return _nf(store.get_case, cid)


@router.get("/cases/{cid}/dem")
def case_dem(cid: str):
    """Re-register the DEM stored with a terrain case so the 3D view can edit and rerun it like a fresh upload."""
    case = _nf(store.get_case, cid)
    inp = case["input"]
    if case["kind"] != "terrain" or "dem_asset" not in inp:
        raise HTTPException(422, "this case has no stored DEM")
    dem = _nf(store.load_dem_asset, case["project_id"], inp["dem_asset"])
    did = f"asset:{case['project_id']}:{inp['dem_asset']}"
    m.DEMS[did] = dem
    return {"dem_id": did, **m._dem_summary(dem)}


@router.patch("/cases/{cid}")
def case_patch(cid: str, p: CasePatch):
    case = _nf(store.get_case, cid)
    if p.input is not None:
        _validate(case["kind"], p.input)
    return _nf(store.update_case, cid, p.name, p.input)


@router.post("/cases/{cid}/duplicate")
def case_duplicate(cid: str, d: DuplicateIn):
    case = _nf(store.get_case, cid)
    new = _nf(store.duplicate_case, cid, d.name, d.overrides)
    try:
        _validate(case["kind"], new["input"])
    except HTTPException:
        store.delete_case(new["id"])
        raise
    return new


@router.delete("/cases/{cid}")
def case_delete(cid: str):
    _nf(store.delete_case, cid)
    return {"deleted": cid}


# ---------------------------------------------------------------------- running
def _comp(c: Any) -> dict | None:
    if not isinstance(c, dict):
        return None
    st = c.get("status")
    if isinstance(st, list):
        st = st[0] if st else None
    code = c.get("code")
    code = code[0] if isinstance(code, list) and code else code
    if st is None:
        st = {1.0: "PASS", 0.0: "FAIL", -1.0: "NO LIMITS", None: "NO DATA"}.get(code)

    def one(v):
        return v[0] if isinstance(v, list) and v and isinstance(v[0], list) else v

    return {"status": st, "margin": one(c.get("margin")), "exceed": one(c.get("exceed")),
            "worstBand": c.get("worstBand"), "worstMargin": c.get("worstMargin"),
            "overallMargin": c.get("overallMargin"), "overallExceed": c.get("overallExceed")}


def _strip(out: dict) -> dict:
    drop = {"fingerprint", "zdiag", "_meta", "profile"}
    return {k: v for k, v in out.items() if k not in drop}


def _kind_name(k: float | None) -> str:
    return {0: "no relevant edge", 1: "blocked: taut-string path", 2: "clear LOS, negative z over crest"}.get(int(k) if k is not None else -1, "")


def _warnings(out: dict) -> list[str]:
    w: list[str] = []
    for key in ("notImplemented",):
        v = out.get(key)
        w += v if isinstance(v, list) else ([v] if v else [])
    sc = (out.get("screen") or {}).get("info") or {}
    for v in (sc.get("warnings"),):
        w += v if isinstance(v, list) else ([v] if v else [])
    en = out.get("enclosure") or {}
    v = en.get("warnings")
    w += v if isinstance(v, list) else ([v] if v else [])
    return w


def _field_points(f: dict, kind: str) -> dict:
    NX, NY = int(f["NX"]), int(f.get("NZ", f.get("NY")))
    ys = f.get("z", f.get("y"))
    codes = (f.get("compliance") or {}).get("code")
    pts = []
    i = 0
    for j in range(NY):
        for xi in range(NX):
            pts.append([f["x"][xi], ys[j], bool(f["valid"][i]), f["Lp_broadband"][i], f["LpA_broadband"][i], None if codes is None else codes[i]])
            i += 1
    return {"kind": kind, "NX": NX, "NY": NY, "n_points": len(pts), "points": pts,
            "stats": {"valid": int(sum(1 for p in pts if p[2])), "LpA_max": max((p[4] for p in pts if p[4] is not None), default=None),
                      "LpA_min": min((p[4] for p in pts if p[4] is not None), default=None)}}


def _run(case: dict) -> tuple[dict, Any, list[str]]:
    kind, inp = case["kind"], case["input"]
    req = inp["request"]
    receivers: list[dict] = []
    field = None
    fingerprint = None
    warnings: list[str] = []
    w = m.state["worker"]

    def lim_payload(lim):
        if not lim:
            return None
        d = dict(lim)
        d["bands"] = [float("nan") if b is None else b for b in (d.get("bands") or [None] * 8)]
        d["overallA"] = float("nan") if d.get("overallA") is None else d["overallA"]
        return d

    if kind == "point":
        j = m.run(m.CaseIn(**req), True)
        fingerprint = j.get("fingerprint")
        receivers.append({"name": (inp.get("receivers") or [{"name": "R1"}])[0]["name"], "x": req["dp"], "y": None, "h": req["hr"], "valid": True,
                          "path": "flat ground", "out": _strip(j), "compliance": _comp(j.get("compliance"))})
        warnings += _warnings(j)
    elif kind == "section":
        q = m.Field2DIn(**req)
        if inp.get("run_field", True):
            f = m.field2d(q, True)
            fingerprint = f.get("fingerprint")
            field = _field_points(f, "section")
        base = {"Lw": req["Lw"], "G": req["G"], "atm": req["atm"], "mode": req.get("mode", "iso2024"),
                "terrain": req["terrain"], "source": {"x": req["source_x"], "h": req["source_h"]}}
        if req.get("enclosure"):
            base["enclosure"] = m._enclosure(q.enclosure)
        if req.get("limits"):
            base["limits"] = lim_payload(req["limits"])
        for rc in inp.get("receivers", []):
            try:
                out = m._json_safe(w.run("run_case_2d", {**base, "receiver": {"x": rc["x"], "h": rc["h"]}}))
                fingerprint = fingerprint or out.get("fingerprint")
                g = out.get("geom") or {}
                receivers.append({"name": rc["name"], "x": rc["x"], "y": None, "h": rc["h"], "valid": True,
                                  "path": {"none": "no relevant edge", "blocked": "blocked: taut-string path", "clear_crest": "clear LOS, negative z over crest"}.get(g.get("kind"), ""),
                                  "out": _strip(out), "compliance": _comp(out.get("compliance")), "geom": g})
                warnings += _warnings(out)
            except Exception as exc:  # noqa: BLE001
                receivers.append({"name": rc["name"], "x": rc.get("x"), "y": None, "h": rc.get("h"), "valid": False, "reason": str(exc)[:300]})
    else:
        dem = store.load_dem_asset(case["project_id"], inp["dem_asset"])
        did = f"asset:{case['project_id']}:{inp['dem_asset']}"
        m.DEMS[did] = dem
        q = m.Field3DIn(**{**req, "dem_id": did})
        if inp.get("run_field", True):
            f = m.field3d(q, True)
            fingerprint = f.get("fingerprint")
            field = _field_points(f, "terrain")
        for rc in inp.get("receivers", []):
            body = m.Case3DIn(dem_id=did, Lw=req["Lw"], G=req["G"], atm=req["atm"], mode=req.get("mode", "iso2024"), source=req["source"],
                              receiver={"x": rc["x"], "y": rc["y"], "h": rc.get("h", req.get("hr", 1.5))}, obstacles=req.get("obstacles", []),
                              limits=req.get("limits"), enclosure=req.get("enclosure"),
                              ground_areas=req.get("ground_areas", []), ground_default=req.get("ground_default"),
                              ground_method=req.get("ground_method", "general"))
            out = m.case3d(body, True)
            fingerprint = fingerprint or (out.get("out") or {}).get("fingerprint")
            if not out.get("valid"):
                receivers.append({"name": rc["name"], "x": rc["x"], "y": rc["y"], "h": rc.get("h"), "valid": False, "reason": out.get("reason", "")})
                continue
            g = out.get("geom") or {}
            receivers.append({"name": rc["name"], "x": rc["x"], "y": rc["y"], "h": rc.get("h", req.get("hr", 1.5)), "valid": True,
                              "path": {"none": "no relevant edge", "blocked": "blocked: taut-string path", "clear_crest": "clear LOS, negative z over crest"}.get(g.get("kind"), ""),
                              "out": _strip(out["out"]), "compliance": _comp(out.get("compliance")), "geom": g, "paths": out.get("paths")})
            warnings += _warnings(out["out"])
    seen: list[str] = []
    for x in warnings:
        if x not in seen:
            seen.append(x)
    result = {"kind": kind, "mode": req.get("mode", "iso2024"), "receivers": receivers, "field": field,
              "notImplemented": [x for x in seen if "not implemented" in x.lower() or "not modelled" in x.lower() or x.startswith(("A_misc", "reflections", "simplified"))]}
    return result, fingerprint, seen


@router.post("/cases/{cid}/run")
def case_run(cid: str):
    case = _nf(store.get_case, cid)
    t0 = time.time()
    try:
        result, fp, warns = _run(case)
    except HTTPException as exc:
        store.set_failed(cid, str(exc.detail))
        raise
    except Exception as exc:  # noqa: BLE001
        store.set_failed(cid, str(exc))
        raise HTTPException(422, f"case failed: {exc}")
    return store.set_result(cid, result, fp, warns, time.time() - t0)


# ------------------------------------------------------------- compare / export
def _cases_for(pid: str, ids: str | None) -> list[dict]:
    wanted = [i for i in (ids or "").split(",") if i]
    rows = store.list_cases(pid)
    pick = [r["id"] for r in rows if (not wanted or r["id"] in wanted)]
    return [store.get_case(i) for i in pick]


@router.get("/projects/{pid}/compare")
def compare(pid: str, case_ids: str | None = None):
    _nf(store.get_project, pid)
    cases = _cases_for(pid, case_ids)
    names: list[str] = []
    for c in cases:
        for q in (c.get("result") or {}).get("receivers", []):
            if q["name"] not in names:
                names.append(q["name"])
    table = []
    for nm in names:
        row: dict[str, Any] = {"receiver": nm, "cases": {}}
        for c in cases:
            q = next((q for q in (c.get("result") or {}).get("receivers", []) if q["name"] == nm), None)
            row["cases"][c["id"]] = None if q is None or not q.get("valid") else {
                "LpA": (q["out"] or {}).get("LpA_broadband"), "Lp": (q["out"] or {}).get("Lp_broadband"),
                "status": (q.get("compliance") or {}).get("status"), "bands": (q["out"] or {}).get("Lp")}
        table.append(row)
    return {"cases": [{"id": c["id"], "name": c["name"], "status": c["status"], "mode": (c["input"].get("request") or {}).get("mode")} for c in cases], "table": table}


@router.get("/projects/{pid}/export.xlsx")
def export_project(pid: str, case_ids: str | None = None, include_grid: bool = False):
    proj = _nf(store.get_project, pid)
    cases = _cases_for(pid, case_ids)
    if not cases:
        raise HTTPException(422, "no cases to export")
    data = export_xlsx.workbook_bytes(proj, cases, include_grid)
    fname = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in proj["name"])[:60] or "project"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})


@router.get("/cases/{cid}/export.csv")
def export_case_csv(cid: str):
    case = _nf(store.get_case, cid)
    return Response(export_xlsx.case_csv(case), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="case.csv"'})
