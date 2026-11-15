"""2D X-Z field evaluation: masking, mirroring symmetry, shadow behind a ridge, consistency."""
import matlab
import pytest

from conftest import mvec

NAN = float("nan")


def base(terrain_x, terrain_z, sx, sh, gx, gz, **extra):
    c = dict(
        Lw=matlab.double([100.0] * 8),
        G={"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
        atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325},
        terrain={"x": matlab.double(terrain_x), "z": matlab.double(terrain_z)},
        source={"x": sx, "h": sh},
        grid={"x": matlab.double(gx), "z": matlab.double(gz)},
    )
    c.update(extra)
    return c


def row(m, k):
    return [float(v) for v in m[k]]


def test_points_inside_ground_are_masked(eng):
    out = eng.run_field_2d(base([0.0, 100.0, 200.0], [0.0, 10.0, 0.0], 0.0, 2.0, [100.0], [5.0, 12.0]))
    valid = [bool(v[0]) for v in out["valid"]]
    assert valid == [False, True]            # (100, 5) is inside the 10 m crest; (100, 12) is above it
    assert all(map(lambda v: v != v, row(out["Lp"], 0)))      # NaN, not a fake level


def test_source_column_and_out_of_domain_are_no_data(eng):
    out = eng.run_field_2d(base([0.0, 200.0], [0.0, 0.0], 50.0, 2.0, [50.0, 300.0, -10.0], [1.5]))
    assert [bool(v[0]) for v in out["valid"]] == [False, False, False]


def test_mirror_symmetry_about_the_source(eng):
    # Flat ground, source at x=100: receivers at 100-60 and 100+60 must match exactly.
    out = eng.run_field_2d(base([0.0, 200.0], [0.0, 0.0], 100.0, 2.0, [40.0, 160.0], [1.5]))
    a, b = row(out["Lp"], 0), row(out["Lp"], 1)
    assert a == pytest.approx(b, abs=1e-9)


def test_mirror_symmetry_with_a_ridge(eng):
    # Symmetric terrain about x=100 with crests at 60 and 140: both sides identical.
    xs = [0.0, 60.0, 100.0, 140.0, 200.0]
    zs = [0.0, 8.0, 0.0, 8.0, 0.0]
    out = eng.run_field_2d(base(xs, zs, 100.0, 2.0, [20.0, 180.0], [4.5]))   # ground there is 2.67 m
    assert row(out["Lp"], 0) == pytest.approx(row(out["Lp"], 1), abs=1e-9)
    assert all(k == 1.0 for k in mvec(out["kind"]))          # both behind a blocking crest


def test_ridge_creates_a_shadow_zone(eng):
    xs = [0.0, 100.0, 200.0]
    flat = eng.run_field_2d(base([0.0, 200.0], [0.0, 0.0], 0.0, 2.0, [150.0], [1.5]))
    ridge = eng.run_field_2d(base(xs, [0.0, 10.0, 0.0], 0.0, 2.0, [150.0], [6.5]))   # ground at 150 m is 5 m
    lf, lr = row(flat["Lp"], 0), row(ridge["Lp"], 0)
    assert lr[4] < lf[4] - 5.0                                # 1 kHz at least 5 dB lower in shadow
    assert max(mvec(ridge["Abar"])) <= 20.0 + 1e-9


def test_field_matches_single_point_run(eng):
    xs, zs = [0.0, 100.0, 200.0], [0.0, 10.0, 0.0]
    f = eng.run_field_2d(base(xs, zs, 0.0, 2.0, [150.0], [6.5]))
    single = eng.run_case_2d(dict(
        Lw=matlab.double([100.0] * 8), G={"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
        atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325},
        terrain={"x": matlab.double(xs), "z": matlab.double(zs)},
        source={"x": 0.0, "h": 2.0}, receiver={"x": 150.0, "h": 1.5}))
    assert row(f["Lp"], 0) == pytest.approx(mvec(single["Lp"]), abs=1e-9)


def test_compliance_codes_on_the_grid(eng):
    lim = {"bands": matlab.double([60.0] * 8), "weighting": "Z", "overallA": NAN}
    out = eng.run_field_2d(base([0.0, 200.0], [0.0, 0.0], 0.0, 2.0, [20.0, 190.0, 0.0], [1.5], limits=lim))
    codes = mvec(out["compliance"]["code"])
    assert codes[0] == 0.0          # 20 m from a 100 dB source: well above 60 dB in some band
    assert codes[1] == 1.0          # 190 m: below
    assert codes[2] != codes[2]     # source column: NO DATA (NaN), not PASS
