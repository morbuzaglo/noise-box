"""Excel and CSV export. One workbook, one sheet per case, plus a Summary sheet.

Every value needed to reproduce a case is written to its sheet: standard edition/mode, inputs, geometry, materials,
limits, per-receiver band spectra and attenuation terms, warnings, limitations and the MATLAB code fingerprint.
Strings are written as text (never as formulas). Sheet names are sanitised to Excel's rules (<= 31 chars, no []:*?/\\).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
A_WEIGHT = [-26.2, -16.1, -8.6, -3.2, 0.0, 1.2, 1.0, -1.1]
MODE_LABEL = {"iso2024": "ISO 9613-2:2024 (published)", "draft2026": "ISO 9613-2:2024 + DAmd 1 eqs. 18/21 (DRAFT, experimental, not an official amendment)"}
BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="DDE3EA")
BAD = Font(color="A32020", bold=True)
EXCEL_MAX_ROWS = 1_048_576
SOFTWARE = "noise-box 0.1"


def safe_sheet_name(name: str, taken: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "-", name).strip().strip("'") or "Case"
    base = base[:31]
    cand, i = base, 2
    while cand.lower() in {t.lower() for t in taken} or cand.lower() == "summary":
        suffix = f" ({i})"
        cand = base[: 31 - len(suffix)] + suffix
        i += 1
    taken.add(cand)
    return cand


def put(ws, r: int, c: int, v: Any, bold: bool = False, fmt: str | None = None):
    cell = ws.cell(row=r, column=c)
    if isinstance(v, bool):
        cell.value = "yes" if v else "no"
    elif isinstance(v, (int, float)):
        cell.value = v if v == v else None          # NaN -> empty
        if fmt:
            cell.number_format = fmt
    elif v is None:
        cell.value = None
    else:
        cell.value = str(v)
        cell.data_type = "s"                        # never let user text become a formula
    if bold:
        cell.font = BOLD
    return cell


def row(ws, r: int, values: list, bold: bool = False, fmt: str | None = None, head: bool = False, start: int = 1):
    for i, v in enumerate(values):
        cell = put(ws, r, start + i, v, bold or head, fmt)
        if head:
            cell.fill = HEAD
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    return r + 1


def ts(t: float | None) -> str:
    return "" if not t else dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _vec(d: dict | None, key: str) -> list:
    v = (d or {}).get(key)
    if isinstance(v, list) and len(v) == 8:
        return v
    if isinstance(v, (int, float)):
        return [v] * 8
    return [None] * 8


def _first(x):
    return x[0] if isinstance(x, list) and x else x


def case_receivers(case: dict) -> list[dict]:
    return (case.get("result") or {}).get("receivers", []) or []


def write_case_sheet(ws, case: dict, project: dict, include_grid_note: bool = True) -> None:
    res = case.get("result") or {}
    inp = case.get("input") or {}
    req = inp.get("request", {})
    mode = req.get("mode", "iso2024")
    r = 1
    put(ws, r, 1, f"Case: {case['name']}", True)
    r += 2
    r = row(ws, r, ["Project", project["name"]])
    r = row(ws, r, ["Case type", {"point": "Flat ground, single receiver", "section": "2D vertical section", "terrain": "3D terrain (DEM)"}[case["kind"]]])
    r = row(ws, r, ["Status", case["status"]])
    r = row(ws, r, ["Executed", ts(case.get("executed"))])
    r = row(ws, r, ["Calculation standard", MODE_LABEL.get(mode, mode)])
    r = row(ws, r, ["Validation status", case.get("validation", "")])
    r = row(ws, r, ["Software", SOFTWARE + " (all acoustic calculation executed in MATLAB)"])
    r = row(ws, r, ["Level conventions", "L_W: dB re 1 pW, unweighted. L_p: dB re 20 uPa. Broadband = energy sum of the eight 63-8000 Hz octave bands only. A-weighting applied per band, then energy-summed."])
    r += 1

    # ---- source
    put(ws, r, 1, "Source", True)
    r += 1
    r = row(ws, r, ["Band, Hz"] + BANDS, head=True)
    lw = req.get("Lw") or _vec(res, "Lw")
    r = row(ws, r, ["L_W unweighted, dB re 1 pW"] + list(lw), fmt="0.0")
    r = row(ws, r, ["A-weighting correction, dB"] + A_WEIGHT, fmt="0.0")
    r = row(ws, r, ["L_W,A, dB(A) re 1 pW"] + [None if v is None else v + a for v, a in zip(lw, A_WEIGHT)], fmt="0.0")
    enc = req.get("enclosure")
    if enc:
        r = row(ws, r, ["Enclosure around source", f"S={enc['S_total']} m2, A_in={enc['A_in']} m2, openings={enc.get('S_open', 0)} m2",
                        "diffuse-field model, rough estimate; material: " + str(enc.get("material"))])
    enc_res = (res.get("receivers") or [{}])[0].get("out", {}).get("enclosure") if res.get("receivers") else None
    if enc_res:
        r = row(ws, r, ["L_W radiated after enclosure"] + _vec(enc_res, "Lw_out"), fmt="0.0")
    r += 1

    # ---- environment
    put(ws, r, 1, "Environment and ground", True)
    r += 1
    atm, G = req.get("atm", {}), req.get("G", {})
    r = row(ws, r, ["Temperature, deg C", atm.get("T_C"), "Relative humidity, %", atm.get("RH"), "Pressure, kPa", atm.get("p_kPa")])
    r = row(ws, r, ["G source", G.get("Gs"), "G middle", G.get("Gm"), "G receiver", G.get("Gr")])
    r = row(ws, r, ["C_met (long-term correction)", "not applied (shown as 0): downwind prediction"])
    r += 1

    # ---- limits
    lim = req.get("limits")
    put(ws, r, 1, "Permitted levels", True)
    r += 1
    if lim and (lim.get("bands") or lim.get("overallA") is not None):
        r = row(ws, r, ["Band, Hz"] + BANDS, head=True)
        r = row(ws, r, [f"Permitted ({'A-weighted' if lim.get('weighting') == 'A' else 'unweighted'}), dB"] + list(lim.get("bands") or [None] * 8), fmt="0.0")
        r = row(ws, r, ["Overall dB(A) limit", lim.get("overallA")])
        r = row(ws, r, ["Rule", "PASS only if every band that has a limit is at or below it, and the overall dB(A) limit (if any) is met."])
    else:
        r = row(ws, r, ["No limits defined"])
    r += 1

    # ---- geometry / obstacles
    put(ws, r, 1, "Scene", True)
    r += 1
    if case["kind"] == "point":
        r = row(ws, r, ["Source height, m", req.get("hs"), "Receiver height, m", req.get("hr"), "Horizontal distance d_p, m", req.get("dp")])
    elif case["kind"] == "section":
        r = row(ws, r, ["Source x, m", req.get("source_x"), "Source height above ground, m", req.get("source_h")])
        t = req.get("terrain", {})
        r = row(ws, r, ["Terrain profile x, m"] + list(t.get("x", [])))
        r = row(ws, r, ["Terrain profile z, m"] + list(t.get("z", [])))
    else:
        s = req.get("source", {})
        r = row(ws, r, ["Source x, y, height above ground (m)", s.get("x"), s.get("y"), s.get("h"), "Receiver height above ground, m", req.get("hr")])
        r = row(ws, r, ["DEM", str(inp.get("dem_info", {}).get("meta", {}).get("source", "")), "CRS", str(inp.get("dem_info", {}).get("crs", "")),
                        "Cell size, m", inp.get("dem_info", {}).get("cs")])
        obs = req.get("obstacles") or []
        if obs:
            r = row(ws, r, ["Obstacle", "Type", "Vertices x", "Vertices y", "Height above ground, m", "Bottom gap, m", "Material (transmission)"], head=True)
            for i, o in enumerate(obs, 1):
                r = row(ws, r, [i, o.get("kind"), ", ".join(f"{v:g}" for v in o.get("x", [])), ", ".join(f"{v:g}" for v in o.get("y", [])),
                                o.get("h"), o.get("gap", 0), str(o.get("material")) if o.get("material") else "opaque (no transmission)"])
    r += 1

    # ---- receivers
    rec = case_receivers(case)
    put(ws, r, 1, "Receivers: predicted levels (dB)", True)
    r += 1
    if not rec:
        r = row(ws, r, ["No results: the case has not been run."])
    else:
        hdr = ["Receiver", "x, m", "y or z, m", "Height above ground, m", "Status", "Worst band, Hz", "Worst margin, dB", "Path", "Broadband L_p, dB", "Broadband L_p,A, dB(A)"]
        hdr += [f"L_p {f} Hz" for f in BANDS] + [f"L_p,A {f} Hz" for f in BANDS]
        r = row(ws, r, hdr, head=True)
        for q in rec:
            o, comp = q.get("out") or {}, q.get("compliance") or {}
            wb = comp.get("worstBand")
            r = row(ws, r, [q.get("name"), q.get("x"), q.get("y"), q.get("h"), comp.get("status") or ("INVALID: " + str(q.get("reason", "")) if not q.get("valid") else "no limits"),
                            BANDS[int(wb) - 1] if wb else None, comp.get("worstMargin") if wb else None, q.get("path"), o.get("Lp_broadband"), o.get("LpA_broadband")]
                    + _vec(o, "Lp") + _vec(o, "LpA_bands"), fmt="0.0")
        r += 1
        terms = [("A_div", "Adiv"), ("A_atm", "Aatm"), ("A_gr (may be negative)", "Agr"), ("A_bar top path", "Abar_top"), ("A_bar lateral left", "Abar_side1"),
                 ("A_bar lateral right", "Abar_side2"), ("A_bar extra path (under gap, engineering ext.)", "Abar_extra"), ("A_bar used (final)", "Abar"),
                 ("A_misc (not modelled)", "Amisc"), ("D_c", "Dc"), ("A total", "Atotal")]
        put(ws, r, 1, "Attenuation terms by receiver and band (dB)", True)
        r += 1
        r = row(ws, r, ["Receiver", "Term"] + [f"{f} Hz" for f in BANDS], head=True)
        for q in rec:
            if not q.get("valid"):
                continue
            for label, key in terms:
                r = row(ws, r, [q.get("name"), label] + _vec(q.get("out"), key), fmt="0.00")
        r += 1
        if limits_present(lim):
            put(ws, r, 1, "Margin = predicted - permitted (dB; positive = exceedance)", True)
            r += 1
            r = row(ws, r, ["Receiver", "Item"] + [f"{f} Hz" for f in BANDS], head=True)
            for q in rec:
                comp = q.get("compliance") or {}
                if not q.get("valid") or not comp:
                    continue
                r = row(ws, r, [q.get("name"), "Margin, dB"] + list(comp.get("margin") or [None] * 8), fmt="0.0")
                r = row(ws, r, [q.get("name"), "Exceeds limit"] + ["yes" if e else "no" for e in (comp.get("exceed") or [False] * 8)])
            r += 1
        screens = [q for q in rec if (q.get("out") or {}).get("screen")]
        if screens:
            put(ws, r, 1, "Transmissive screen (ENGINEERING APPROXIMATION, not prescribed by ISO 9613-2)", True)
            r += 1
            r = row(ws, r, ["Receiver", "Quantity"] + [f"{f} Hz" for f in BANDS], head=True)
            for q in screens:
                sc = q["out"]["screen"]
                for label, key in [("A_bar opaque (ISO), dB", "Abar_opaque"), ("TL, dB", "TL"), ("A_eff, dB", "A_eff"),
                                   ("Level via diffraction, dB", "L_diffracted"), ("Level via transmission, dB", "L_transmitted")]:
                    r = row(ws, r, [q.get("name"), label] + _vec(sc, key), fmt="0.00")
                r = row(ws, r, [q.get("name"), "Opaque assumption OK (TL - A_bar >= 10 dB rule of thumb)", sc.get("opaqueAssumptionOK")])
                for w in (sc.get("info") or {}).get("warnings", []) if isinstance((sc.get("info") or {}).get("warnings"), list) else []:
                    r = row(ws, r, [q.get("name"), "Warning", w])
            r += 1

    # ---- limitations, warnings, code
    put(ws, r, 1, "Limitations and warnings", True)
    r += 1
    seen = set()
    for w in list(case.get("warnings") or []) + list((res.get("notImplemented") or [])):
        if w not in seen:
            seen.add(w)
            r = row(ws, r, [w])
    if mode == "draft2026":
        r = row(ws, r, ["DRAFT AMENDMENT MODE: eqs. (18) and (21) replaced per the DAmd 1 screenshot; results are experimental and not ISO-conformant."])
    if include_grid_note and res.get("field"):
        r = row(ws, r, [f"Map grid with {res['field'].get('n_points', 0)} points is stored in the case; export it with include_grid=true (separate sheet)."])
    r += 1
    put(ws, r, 1, "MATLAB code fingerprint (md5 of each .m file used)", True)
    r += 1
    fp = case.get("fingerprint") or {}
    files, md5s = fp.get("file", []), fp.get("md5", [])
    if isinstance(files, str):
        files, md5s = [files], [md5s]
    r = row(ws, r, ["File", "MD5"], head=True)
    for f, m in zip(files, md5s):
        r = row(ws, r, [f, m])
    for col in range(1, 40):
        ws.column_dimensions[get_column_letter(col)].width = 16 if col > 1 else 44
    ws.freeze_panes = "B3"


def limits_present(lim: dict | None) -> bool:
    return bool(lim) and (any(b is not None for b in (lim.get("bands") or [])) or lim.get("overallA") is not None)


def write_grid_sheet(ws, case: dict) -> bool:
    f = (case.get("result") or {}).get("field")
    if not f or not f.get("points"):
        return False
    pts = f["points"]
    if len(pts) + 2 > EXCEL_MAX_ROWS:
        put(ws, 1, 1, f"Grid has {len(pts)} rows, above Excel's row limit; export as CSV instead.")
        return True
    r = row(ws, 1, ["x, m", "y or z, m", "valid", "Broadband L_p, dB", "Broadband L_p,A, dB(A)", "Compliance"], head=True)
    for p in pts:
        r = row(ws, r, [p[0], p[1], p[2], p[3], p[4], p[5]], fmt="0.0")
    return True


def build_workbook(project: dict, cases: list[dict], include_grid: bool = False) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    taken: set[str] = {"Summary"}
    sheets = []
    for c in cases:
        name = safe_sheet_name(c["name"], taken)
        sheets.append((name, c))
    r = 1
    put(ws, r, 1, "Noise Box project export", True)
    r += 2
    r = row(ws, r, ["Project", project["name"]])
    r = row(ws, r, ["Description", project.get("description", "")])
    r = row(ws, r, ["Created", ts(project.get("created"))])
    r = row(ws, r, ["Exported", ts(dt.datetime.now(dt.timezone.utc).timestamp())])
    r = row(ws, r, ["Software", SOFTWARE])
    r = row(ws, r, ["Notes", "Predictions use ISO 9613-2:2024 downwind conditions unless a case says otherwise. Results from self-authored tests only; no ISO conformance or certification is claimed."])
    r += 1
    put(ws, r, 1, "Cases", True)
    r += 1
    r = row(ws, r, ["Sheet", "Case", "Type", "Standard / mode", "Status", "Executed", "Receivers", "Overall status", "Code (first file md5)"], head=True)
    for name, c in sheets:
        rec = case_receivers(c)
        statuses = [(q.get("compliance") or {}).get("status") for q in rec if q.get("valid")]
        overall = "no limits" if not any(statuses) else ("FAIL" if "FAIL" in statuses else ("PASS" if all(s == "PASS" for s in statuses if s) else "NO DATA"))
        fp = c.get("fingerprint") or {}
        md5 = (fp.get("md5") or [""])[0] if isinstance(fp.get("md5"), list) else fp.get("md5", "")
        r = row(ws, r, [name, c["name"], c["kind"], MODE_LABEL.get((c.get("input", {}).get("request") or {}).get("mode", "iso2024")), c["status"], ts(c.get("executed")),
                        len(rec), overall, md5])
    r += 1
    # ---- comparison: broadband dB(A) by receiver and case, with live difference formulas
    put(ws, r, 1, "Comparison across receivers and cases: broadband L_p,A, dB(A) (63-8000 Hz bands)", True)
    r += 1
    names: list[str] = []
    for _, c in sheets:
        for q in case_receivers(c):
            if q.get("name") not in names:
                names.append(q.get("name"))
    head = ["Receiver"] + [n for n, _ in sheets]
    head_row = r
    r = row(ws, r, head, head=True)
    first_data = r
    for nm in names:
        vals = [nm]
        for _, c in sheets:
            q = next((q for q in case_receivers(c) if q.get("name") == nm), None)
            vals.append((q.get("out") or {}).get("LpA_broadband") if q and q.get("valid") else None)
        r = row(ws, r, vals, fmt="0.0")
    last_data = r - 1
    if len(sheets) > 1 and names:
        r += 1
        put(ws, r, 1, "Difference to the first case, dB (live formulas)", True)
        r += 1
        r = row(ws, r, ["Receiver"] + [n for n, _ in sheets[1:]], head=True)
        for i, nm in enumerate(names):
            src = first_data + i
            put(ws, r, 1, nm)
            for j in range(1, len(sheets)):
                col = get_column_letter(j + 2)
                cell = ws.cell(row=r, column=j + 1)
                cell.value = f'=IF(OR(ISBLANK({col}{src}),ISBLANK($B{src})),"",{col}{src}-$B{src})'
                cell.number_format = "0.0"
            r += 1
    for col in range(1, 12):
        ws.column_dimensions[get_column_letter(col)].width = 24 if col > 1 else 30

    for name, c in sheets:
        wsc = wb.create_sheet(name)
        write_case_sheet(wsc, c, project)
        if include_grid and (c.get("result") or {}).get("field"):
            gname = safe_sheet_name(f"{name[:25]} grid", taken)
            write_grid_sheet(wb.create_sheet(gname), c)
    return wb


def workbook_bytes(project: dict, cases: list[dict], include_grid: bool = False) -> bytes:
    bio = io.BytesIO()
    build_workbook(project, cases, include_grid).save(bio)
    return bio.getvalue()


def case_csv(case: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["receiver", "x_m", "y_or_z_m", "height_m", "status", "valid"] + [f"Lp_{f}Hz_dB" for f in BANDS] + [f"LpA_{f}Hz_dBA" for f in BANDS] + ["Lp_broadband_dB", "LpA_broadband_dBA"])
    for q in case_receivers(case):
        o = q.get("out") or {}
        st = (q.get("compliance") or {}).get("status", "")
        w.writerow([_csv(q.get("name")), q.get("x"), q.get("y"), q.get("h"), st, q.get("valid")] + _vec(o, "Lp") + _vec(o, "LpA_bands") + [o.get("Lp_broadband"), o.get("LpA_broadband")])
    return out.getvalue()


def _csv(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in "=+-@" else s
