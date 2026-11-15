"""3D DEM mode: profile extraction and field evaluation, checked against hand geometry."""
import math

import matlab
import pytest

from conftest import mvec

NAN = float("nan")


def ridge_dem(nx=21, ny=11, cs=10.0, nan_cell=None):
    """z = 10 - |x-100|/10 (crest 10 m at x=100, 0 m at x=0 and x=200), constant in y."""
    Z = [[10.0 - abs(ix * cs - 100.0) / 10.0 for ix in range(nx)] for _ in range(ny)]
    if nan_cell is not None:
        iy, ix = nan_cell
        Z[iy][ix] = NAN
    return {"x0": 0.0, "y0": 0.0, "cs": cs, "Z": matlab.double(Z)}


def case(dem, sx, sy, gx, gy, **extra):
    c = dict(
        Lw=matlab.double([100.0] * 8),
        G={"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
        atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325},
        dem=dem, source={"x": sx, "y": sy, "h": 2.0},
        grid={"x": matlab.double(gx), "y": matlab.double(gy)}, hr=1.5,
    )
    c.update(extra)
    return c


def blist(x):
    """MATLAB logical (1x1 -> bool, column -> list of [bool]) -> flat list of bool."""
    if isinstance(x, bool):
        return [x]
    return [bool(v[0]) if hasattr(v, "__len__") else bool(v) for v in x]


def test_dem_sampling_is_exact_on_the_linear_ridge(eng):
    dem = ridge_dem()
    xs = [0.0, 25.0, 100.0, 133.0, 200.0]
    z = mvec(eng.nb_dem_sample(dem, matlab.double(xs), matlab.double([50.0] * 5)))
    assert z == pytest.approx([10 - abs(x - 100) / 10 for x in xs], abs=1e-9)


def test_dem_sampling_outside_or_nan_is_nan(eng):
    dem = ridge_dem(nan_cell=(5, 10))
    z = mvec(eng.nb_dem_sample(dem, matlab.double([-1.0, 205.0, 100.0]), matlab.double([50.0, 50.0, 50.0])))
    assert all(v != v for v in z)               # outside, outside, and a NaN corner


def test_profile_along_x_matches_hand_geometry(eng):
    dem = ridge_dem()
    s, z, ok = eng.nb_profile_dem(dem, matlab.double([0.0, 50.0]), matlab.double([150.0, 50.0]), nargout=3)
    s, z = mvec(s), mvec(z)
    assert bool(ok) and s[0] == 0.0 and s[-1] == pytest.approx(150.0)
    assert z == pytest.approx([10 - abs(v - 100) / 10 for v in s], abs=1e-9)


def test_oblique_ridge_crossing_geometry(eng):
    # S=(0,0), R=(150,150). In the vertical plane the crest is at s = 100*sqrt2 (height 10).
    dem = ridge_dem(nx=21, ny=21)
    Sxy, Rxy = [0.0, 0.0], [150.0, 150.0]
    s, z, ok = eng.nb_profile_dem(dem, matlab.double(Sxy), matlab.double(Rxy), nargout=3)
    s, z = mvec(s), mvec(z)
    L = 150 * math.sqrt(2)
    assert s[-1] == pytest.approx(L)
    g = eng.nb_geom2d(matlab.double(s), matlab.double(z), matlab.double([0.0, 0.0 + 2.0]),
                      matlab.double([L, 5.0 + 1.5]))
    # Independent construction: crest E = (100*sqrt2, 10)
    ex = 100 * math.sqrt(2)
    dss = math.hypot(ex, 10 - 2.0)
    dsr = math.hypot(L - ex, 10 - 6.5)
    d = math.hypot(L, 6.5 - 2.0)
    assert g["kind"] == "blocked"
    # The crest lies on the grid line x = 100, which the line crosses at s = 100*sqrt2: it is sampled exactly.
    assert float(g["z"]) == pytest.approx(dss + dsr - d, abs=1e-9)
    assert float(g["dss"]) == pytest.approx(dss, abs=1e-9)


def test_3d_field_matches_2d_pipeline_for_same_ridge(eng):
    dem = ridge_dem()
    f3 = eng.run_field_3d(case(dem, 0.0, 50.0, [150.0], [50.0]))
    f2 = eng.run_case_2d(dict(
        Lw=matlab.double([100.0] * 8), G={"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
        atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325},
        terrain={"x": matlab.double([0.0, 100.0, 200.0]), "z": matlab.double([0.0, 10.0, 0.0])},
        source={"x": 0.0, "h": 2.0}, receiver={"x": 150.0, "h": 1.5}))
    a = [float(v) for v in f3["Lp"][0]]
    assert a == pytest.approx(mvec(f2["Lp"]), abs=1e-6)


def test_receivers_follow_the_terrain_and_report_ground(eng):
    dem = ridge_dem()
    f = eng.run_field_3d(case(dem, 0.0, 50.0, [20.0, 100.0, 180.0], [50.0]))
    assert mvec(f["ground"]) == pytest.approx([2.0, 10.0, 2.0], abs=1e-9)
    assert all(bool(v[0]) for v in f["valid"])


def test_nan_on_the_path_means_no_data(eng):
    # NaN cell at x=100 (ix=10) on the line y=50 (iy=5): receivers beyond it have no valid profile.
    dem = ridge_dem(nan_cell=(5, 10))
    f = eng.run_field_3d(case(dem, 0.0, 50.0, [50.0, 150.0], [50.0]))
    valid = [bool(v[0]) for v in f["valid"]]
    assert valid == [True, False]
    assert all(v != v for v in [float(t) for t in f["Lp"][1]])


def test_outside_grid_receiver_is_masked_and_source_outside_errors(eng):
    dem = ridge_dem()
    f = eng.run_field_3d(case(dem, 0.0, 50.0, [250.0], [50.0]))
    assert blist(f["valid"]) == [False]
    with pytest.raises(matlab.engine.MatlabExecutionError):
        eng.run_field_3d(case(dem, -50.0, 50.0, [100.0], [50.0]))


def test_flat_dem_has_no_edges_and_no_screening(eng):
    flat = {"x0": 0.0, "y0": 0.0, "cs": 10.0, "Z": matlab.double([[0.0] * 21 for _ in range(11)])}
    f = eng.run_field_3d(case(flat, 0.0, 50.0, [60.0, 120.0, 190.0], [50.0, 20.0]))
    assert all(k == 0.0 for k in mvec(f["kind"]))
    assert max(max(float(v) for v in row) for row in f["Abar"]) == 0.0


def test_ridge_shadow_in_3d(eng):
    dem = ridge_dem()
    f = eng.run_field_3d(case(dem, 0.0, 50.0, [60.0, 150.0], [50.0]))
    kinds = mvec(f["kind"])
    assert kinds[0] in (0.0, 2.0) and kinds[1] == 1.0
    assert max(float(v) for v in f["Abar"][1]) > 5.0
