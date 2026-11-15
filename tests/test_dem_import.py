"""DEM import: orientation, CRS handling, units, no-data. No MATLAB needed except the API test."""
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import dem as D  # noqa: E402

ASC = """ncols 3
nrows 2
xllcorner 1000
yllcorner 2000
cellsize 10
NODATA_value -9999
10 20 -9999
1 2 3
"""


def test_esri_ascii_orientation_and_nodata():
    d = D.load_esri_ascii(ASC.encode(), "m", True)
    # File rows are north-to-south, so the LAST file row is the southern row (iy = 0).
    assert d["Z"][0].tolist() == [1, 2, 3]
    assert d["Z"][1][:2].tolist() == [10, 20] and np.isnan(d["Z"][1][2])
    # corner (1000, 2000) -> centre of cell (0,0) is (1005, 2005)
    assert (d["x0"], d["y0"], d["cs"]) == (1005.0, 2005.0, 10.0)


def test_vertical_unit_conversion_feet():
    d = D.load_esri_ascii(ASC.encode(), "ft", True)
    assert d["Z"][0, 0] == pytest.approx(0.3048)


def test_vertical_unit_is_mandatory():
    with pytest.raises(D.DemError, match="vertical unit"):
        D.load_esri_ascii(ASC.encode(), None, True)


def test_ascii_without_metric_declaration_is_rejected():
    with pytest.raises(D.DemError, match="no CRS"):
        D.load_esri_ascii(ASC.encode(), "m", False)


def test_degrees_are_never_treated_as_metres():
    deg = ASC.replace("xllcorner 1000", "xllcorner 35.0").replace("yllcorner 2000", "yllcorner 32.0").replace("cellsize 10", "cellsize 0.0001")
    with pytest.raises(D.DemError, match="degrees"):
        D.load_esri_ascii(deg.encode(), "m", True)


def test_xyz_regular_grid():
    rows = "\n".join(f"{x},{y},{x + 10 * y}" for y in (0, 5, 10) for x in (0, 5, 10, 15))
    d = D.load_xyz(("x,y,z\n" + rows).encode(), "m", True)
    assert d["Z"].shape == (3, 4) and d["cs"] == 5.0
    assert d["Z"][2, 3] == 15 + 100


def test_xyz_irregular_cloud_is_rejected_not_interpolated():
    rows = "0,0,1\n1,0,1\n0,1,1\n1.5,1.5,1\n7,3,2\n"
    with pytest.raises(D.DemError, match="regular"):
        D.load_xyz(rows.encode(), "m", True)


def test_xyz_missing_points_become_nan():
    rows = "\n".join(f"{x},{y},1" for y in (0, 5, 10) for x in (0, 5, 10) if not (x == 5 and y == 5))
    d = D.load_xyz(rows.encode(), "m", True)
    assert np.isnan(d["Z"][1, 1]) and not np.isnan(d["Z"][0, 0])


def _write_tif(path, arr, crs, transform):
    import rasterio

    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype="float32", crs=crs, transform=transform, nodata=-9999.0) as dst:
        dst.write(arr.astype("float32"), 1)


def test_geotiff_projected_utm(tmp_path):
    from rasterio.transform import from_origin

    arr = np.arange(12, dtype=float).reshape(3, 4)          # rows north-to-south
    p = tmp_path / "utm.tif"
    _write_tif(p, arr, "EPSG:32636", from_origin(700000.0, 3550000.0, 10.0, 10.0))
    d = D.load_geotiff(p, "m")
    assert d["crs"] == "EPSG:32636" and d["cs"] == 10.0
    assert d["Z"][0].tolist() == arr[-1].tolist()            # south row first
    assert d["x0"] == 700005.0 and d["y0"] == 3550000.0 - 30.0 + 5.0


def test_geotiff_geographic_is_reprojected_to_metric_utm(tmp_path):
    from rasterio.transform import from_origin

    arr = np.full((40, 40), 100.0)
    p = tmp_path / "geo.tif"
    _write_tif(p, arr, "EPSG:4326", from_origin(35.000, 32.010, 0.00025, 0.00025))   # ~ 25 m cells
    d = D.load_geotiff(p, "m")
    assert d["crs"] == "EPSG:32636"                                           # UTM zone 36N for lon 35 E
    assert 20.0 < d["cs"] < 30.0                                              # metres, not 0.00025
    assert any("reprojected" in n for n in d["meta"]["notes"])
    assert np.nanmax(d["Z"]) == pytest.approx(100.0)


def test_geotiff_without_crs_is_rejected(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    p = tmp_path / "nocrs.tif"
    with rasterio.open(p, "w", driver="GTiff", height=3, width=3, count=1, dtype="float32",
                       transform=from_origin(0, 30, 10, 10)) as dst:
        dst.write(np.ones((3, 3), dtype="float32"), 1)
    with pytest.raises(D.DemError, match="no CRS"):
        D.load_geotiff(p, "m")


def test_synthetic_is_labelled():
    d = D.synthetic("hill")
    assert "SYNTHETIC" in d["meta"]["notes"][0]
    assert d["Z"].max() == pytest.approx(14.0, rel=0.02)


def test_oversized_dem_is_rejected():
    with pytest.raises(D.DemError, match="too large"):
        D._finish(np.zeros((2100, 2100)), 0, 0, 1.0, "x", {})
