"""DEM / DTM import. Output is the plain grid the MATLAB core expects.

Normalised DEM dict (all lengths in METRES, elevations in METRES):
    x0, y0   coordinates of the CENTRE of cell (iy=0, ix=0) in the projected CRS
    cs       cell size (square cells)
    Z        list of NY rows of NX floats, row index increasing with y (south to north);
             NaN is stored as None in JSON and means NO DATA
    crs      e.g. "EPSG:32636" or "declared-metric" when the file carries no CRS
    meta     source file name, original CRS, vertical unit/datum as declared, notes

Rules (brief, "Terrain, coordinates and scene editor"):
  * Never treat latitude/longitude degrees as metres. A geographic CRS is reprojected
    to the UTM zone of the grid centre; a file without CRS must be declared metric.
  * Vertical unit must be stated explicitly; it is converted to metres.
  * NaN / nodata cells are kept as NaN, never filled.
"""
from __future__ import annotations

import csv
import io
import math
import pathlib
import re

import numpy as np

VERTICAL_UNITS = {"m": 1.0, "metre": 1.0, "meter": 1.0, "ft": 0.3048, "foot": 0.3048, "us-ft": 1200 / 3937}
MAX_CELLS = 4_000_000


class DemError(ValueError):
    pass


def _finish(Z: np.ndarray, x0: float, y0: float, cs: float, crs: str, meta: dict) -> dict:
    if Z.ndim != 2 or min(Z.shape) < 2:
        raise DemError("DEM needs at least 2 x 2 cells")
    if Z.size > MAX_CELLS:
        raise DemError(f"DEM too large: {Z.size} cells (max {MAX_CELLS}); crop or resample it first")
    if not np.isfinite(cs) or cs <= 0:
        raise DemError("cell size must be positive")
    if np.all(np.isnan(Z)):
        raise DemError("DEM contains no valid elevation cells")
    return {"x0": float(x0), "y0": float(y0), "cs": float(cs), "Z": Z, "crs": crs, "meta": meta}


def _vertical_factor(unit: str | None) -> float:
    if unit is None:
        raise DemError("vertical unit must be stated explicitly (m, ft or us-ft)")
    try:
        return VERTICAL_UNITS[unit.lower()]
    except KeyError:
        raise DemError(f"unknown vertical unit '{unit}'") from None


def _looks_geographic(x0: float, y0: float, cs: float, nx: int, ny: int) -> bool:
    return abs(x0) <= 360 and abs(y0) <= 90 and abs(x0 + cs * nx) <= 360 and abs(y0 + cs * ny) <= 90 and cs < 0.1


def load_esri_ascii(data: bytes, vertical_unit: str | None, declared_metric: bool, name: str = "grid.asc") -> dict:
    f = _vertical_factor(vertical_unit)
    text = data.decode("utf-8", errors="replace").splitlines()
    hdr: dict[str, float] = {}
    i = 0
    while i < len(text) and text[i].split() and re.fullmatch(r"[A-Za-z_]+", text[i].split()[0]):
        k, v = text[i].split()[:2]
        hdr[k.lower()] = float(v)
        i += 1
    need = {"ncols", "nrows", "cellsize"}
    if not need <= hdr.keys() or not ({"xllcorner", "yllcorner"} <= hdr.keys() or {"xllcenter", "yllcenter"} <= hdr.keys()):
        raise DemError("ESRI ASCII header is incomplete (ncols, nrows, cellsize, xll/yll corner or center)")
    nx, ny, cs = int(hdr["ncols"]), int(hdr["nrows"]), hdr["cellsize"]
    nodata = hdr.get("nodata_value", -9999.0)
    vals = np.array(" ".join(text[i:]).split(), dtype=float)
    if vals.size != nx * ny:
        raise DemError(f"ESRI ASCII has {vals.size} values, expected {nx * ny}")
    Z = vals.reshape(ny, nx)[::-1].copy()  # file rows are north-to-south
    Z[Z == nodata] = np.nan
    Z *= f
    if "xllcenter" in hdr:
        x0, y0 = hdr["xllcenter"], hdr["yllcenter"]
    else:
        x0, y0 = hdr["xllcorner"] + cs / 2, hdr["yllcorner"] + cs / 2
    if _looks_geographic(x0, y0, cs, nx, ny):
        raise DemError("grid looks like latitude/longitude degrees (ESRI ASCII carries no CRS). "
                       "Reproject to a metric CRS first, or supply a GeoTIFF with CRS metadata.")
    if not declared_metric:
        raise DemError("ESRI ASCII has no CRS: confirm that horizontal units are metres (declared_metric=true)")
    return _finish(Z, x0, y0, cs, "declared-metric", {"source": name, "format": "esri-ascii", "vertical_unit": vertical_unit, "nodata": nodata})


def load_xyz(data: bytes, vertical_unit: str | None, declared_metric: bool, name: str = "points.xyz") -> dict:
    """Regular-grid XYZ / CSV (x, y, z per row). Irregular point clouds are rejected, not interpolated."""
    f = _vertical_factor(vertical_unit)
    if not declared_metric:
        raise DemError("XYZ/CSV carries no CRS: confirm that horizontal units are metres (declared_metric=true)")
    rows = []
    for line in csv.reader(io.StringIO(data.decode("utf-8", errors="replace")), delimiter=","):
        if len(line) == 1:
            line = line[0].split()
        try:
            rows.append([float(v) for v in line[:3]])
        except ValueError:
            continue  # header or junk line
    if len(rows) < 4:
        raise DemError("no numeric x,y,z rows found")
    a = np.array(rows)
    xs, ys = np.unique(a[:, 0]), np.unique(a[:, 1])
    if len(xs) < 2 or len(ys) < 2:
        raise DemError("need at least 2 distinct x and 2 distinct y values")
    dxs, dys = np.diff(xs), np.diff(ys)
    cs = float(np.median(dxs))
    if not (np.allclose(dxs, cs, rtol=1e-6, atol=1e-9) and np.allclose(dys, cs, rtol=1e-6, atol=1e-9)):
        raise DemError("XYZ points do not form a regular square grid; interpolating a scattered cloud is not done silently")
    Z = np.full((len(ys), len(xs)), np.nan)
    ix = np.rint((a[:, 0] - xs[0]) / cs).astype(int)
    iy = np.rint((a[:, 1] - ys[0]) / cs).astype(int)
    Z[iy, ix] = a[:, 2] * f
    return _finish(Z, xs[0], ys[0], cs, "declared-metric", {"source": name, "format": "xyz", "vertical_unit": vertical_unit})


def load_geotiff(path: str | pathlib.Path, vertical_unit: str | None, name: str | None = None) -> dict:
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject
    from pyproj import CRS, Transformer

    f = _vertical_factor(vertical_unit)
    with rasterio.open(path) as src:
        if src.crs is None:
            raise DemError("GeoTIFF has no CRS; cannot establish metric coordinates")
        band = src.read(1, masked=True).astype(float)
        Z = np.ma.filled(band, np.nan)
        crs = CRS.from_user_input(src.crs)
        transform = src.transform
        notes = []
        if crs.is_geographic:
            cx, cy = src.xy(src.height // 2, src.width // 2)
            zone = int((cx + 180) // 6) + 1
            utm = CRS.from_epsg((32600 if cy >= 0 else 32700) + zone)
            tr, w, h = calculate_default_transform(src.crs, utm, src.width, src.height, *src.bounds)
            out = np.full((h, w), np.nan)
            reproject(Z, out, src_transform=src.transform, src_crs=src.crs, dst_transform=tr, dst_crs=utm,
                      src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
            Z, transform, crs = out, tr, utm
            notes.append(f"reprojected from geographic CRS to {utm.to_string()}")
        axis_unit = crs.axis_info[0].unit_conversion_factor if crs.axis_info else 1.0
        if abs(axis_unit - 1.0) > 1e-9:
            raise DemError(f"CRS horizontal unit is not metres (factor {axis_unit}); reproject to a metric CRS")
        csx, csy = abs(transform.a), abs(transform.e)
        if abs(csx - csy) > 1e-6 * csx:
            raise DemError("non-square cells are not supported")
        if transform.b != 0 or transform.d != 0:
            raise DemError("rotated rasters are not supported")
        Z = Z[::-1].copy() * f  # GeoTIFF rows are north-to-south
        x0 = transform.c + csx / 2
        y0 = transform.f - csy * (Z.shape[0] - 0.5)  # centre of the south-most row
        return _finish(Z, x0, y0, csx, crs.to_string(), {"source": name or str(path), "format": "geotiff",
                                                         "vertical_unit": vertical_unit, "notes": notes})


def synthetic(kind: str, nx: int = 61, ny: int = 61, cs: float = 5.0, x0: float = 0.0, y0: float = 0.0) -> dict:
    """Synthetic terrain for demos and tests (clearly labelled, not real survey data)."""
    xs = np.arange(nx) * cs
    ys = np.arange(ny) * cs
    X, Y = np.meshgrid(xs, ys)   # local coordinates; the grid origin is shifted below
    if kind == "flat":
        Z = np.zeros_like(X)
    elif kind == "ridge":
        Z = np.maximum(0.0, 10.0 - np.abs(X - xs[-1] / 2) / 6.0)
    elif kind == "hill":
        r2 = (X - xs[-1] / 2) ** 2 + (Y - ys[-1] / 2) ** 2
        Z = 14.0 * np.exp(-r2 / (2 * (0.16 * xs[-1]) ** 2))
    else:
        raise DemError(f"unknown synthetic terrain '{kind}'")
    return _finish(Z, x0, y0, cs, "synthetic-metric", {"source": f"synthetic:{kind}", "format": "synthetic",
                                                         "notes": ["SYNTHETIC terrain, not survey data"]})


def to_payload(dem: dict) -> dict:
    """JSON-safe copy (NaN -> None) for the browser."""
    Z = dem["Z"]
    return {**{k: dem[k] for k in ("x0", "y0", "cs", "crs", "meta")},
            "nx": int(Z.shape[1]), "ny": int(Z.shape[0]),
            "Z": [[None if not math.isfinite(v) else float(v) for v in row] for row in Z]}


def to_matlab(dem: dict) -> dict:
    """Plain structure for the MATLAB worker (NaN stays NaN)."""
    return {"x0": dem["x0"], "y0": dem["y0"], "cs": dem["cs"], "Z": [[float(v) for v in row] for row in dem["Z"]]}
