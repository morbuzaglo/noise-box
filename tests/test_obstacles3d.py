"""Finite walls and buildings: top + lateral diffraction, ISO 9613-2:2024 7.4.1, 7.4.3, 7.4.4.

Expected geometry is constructed by hand for each scene (Pythagoras in the vertical
and the lateral plane). The barrier attenuation is re-derived here from the printed
Formulae (16)-(21) and (25) in plain Python and compared band by band.
"""
import math

import matlab
import pytest

from conftest import mvec

F = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


def dz2024(z, dss, dsr, d, e, f, lateral):
    lam = 340.0 / f
    c2 = 20.0
    c3 = 1.0 if e == 0 else (1 + (5 * lam / e) ** 2) / (1 / 3 + (5 * lam / e) ** 2)
    zmin = -2 * lam / (c2 * c3)
    if z <= zmin:
        return 0.0
    kmet = 1.0 if lateral else math.exp(-(1 / 2000) * math.sqrt((max(dss, dsr) + e) * min(dss, dsr) * d / (2 * (z - zmin))))
    dz = 10 * math.log10(1 + (2 + (c2 / lam) * c3 * z) * kmet)
    return dz if lateral else min(dz, 20.0 if e == 0 else 25.0)


def abar_expected(top, sides, agr):
    out = []
    for i, f in enumerate(F):
        terms = []
        a_top = top(f) - (agr[i] if agr[i] > 0 else 0.0)
        terms.append(10 ** (-0.1 * max(a_top, 0.0)))
        for s in sides:
            terms.append(10 ** (-0.1 * max(s(f), 0.0)))
        out.append(max(-10 * math.log10(sum(terms)), 0.0))
    return out


def flat_dem(n=41, cs=10.0, z=0.0):
    return {"x0": 0.0, "y0": 0.0, "cs": cs, "Z": matlab.double([[z] * n for _ in range(n)])}


def ridge_x_dem(xcrest, hcrest, n=41, cs=10.0):
    row = [max(0.0, hcrest - abs(ix * cs - xcrest) * hcrest / 50.0) for ix in range(n)]
    return {"x0": 0.0, "y0": 0.0, "cs": cs, "Z": matlab.double([row for _ in range(n)])}


def wall(x1, y1, x2, y2, top):
    return {"x": matlab.double([x1, x2]), "y": matlab.double([y1, y2]), "top": float(top)}


def building(x0, x1, y0, y1, top):
    return {"x": matlab.double([x0, x1, x1, x0]), "y": matlab.double([y0, y0, y1, y1]), "top": float(top)}


def case(dem, obstacles, **extra):
    c = dict(
        Lw=matlab.double([100.0] * 8),
        G={"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
        atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325},
        dem=dem, source={"x": 100.0, "y": 200.0, "h": 2.0},
        receiver={"x": 300.0, "y": 200.0, "h": 1.5}, obstacles=obstacles,
    )
    c.update(extra)
    return c


S_Z, R_Z, D = 2.0, 1.5, math.hypot(200.0, 0.5)


def test_thin_finite_wall_top_and_both_lateral_paths(eng):
    r = eng.run_case_3d(case(flat_dem(), [wall(200, 190, 200, 210, 5.0)]))
    assert bool(r["valid"])
    g = r["geom"]
    # top path: single edge at mid-path, height 5 m
    dss, dsr = math.hypot(100, 5 - S_Z), math.hypot(100, 5 - R_Z)
    assert g["kind"] == "blocked" and float(g["e"]) == 0.0
    assert float(g["dss"]) == pytest.approx(dss, abs=1e-6)
    assert float(g["z"]) == pytest.approx(dss + dsr - D, abs=1e-6)
    # lateral paths: vertical edges at the wall ends, v = +-10 m, u from the lateral-plane intersection
    u = (100 * 200 + 0.125) / D            # rel = (100, +-10, -0.25), e = (200, 0, -0.5)/D
    zl = math.hypot(u, 10) + math.hypot(D - u, 10) - D
    for side in ("left", "right"):
        s = g["lateral"][side]
        assert bool(s["valid"]), s
        assert float(s["z"]) == pytest.approx(zl, abs=1e-6)
        assert float(s["e"]) == 0.0
    # band-by-band A_bar from Formulae (16), (17), (25)
    agr = mvec(r["out"]["Agr"])
    exp = abar_expected(
        lambda f: dz2024(dss + dsr - D, dss, dsr, D, 0.0, f, False),
        [lambda f: dz2024(zl, 0, 0, D, 0.0, f, True)] * 2, agr)
    assert mvec(r["out"]["Abar"]) == pytest.approx(exp, abs=1e-6)


def test_lateral_paths_reduce_barrier_attenuation_vs_top_only(eng):
    # A very long wall (|v| = 100 m) fails the factor-8 rule -> top path only.
    short = eng.run_case_3d(case(flat_dem(), [wall(200, 190, 200, 210, 5.0)]))
    longw = eng.run_case_3d(case(flat_dem(), [wall(200, 100, 200, 300, 5.0)]))
    a_s, a_l = mvec(short["out"]["Abar"]), mvec(longw["out"]["Abar"])
    assert all(s <= l + 1e-9 for s, l in zip(a_s, a_l))        # lateral energy can only reduce A_bar
    assert a_s != a_l


def test_factor_eight_rule_neglects_far_lateral_edges(eng):
    r = eng.run_case_3d(case(flat_dem(), [wall(200, 100, 200, 300, 5.0)]))
    lt = r["geom"]["lateral"]
    vd = 650.0 / math.hypot(200, 0.5)                  # vertical-plane support distance, hand-derived (3.25 m)
    assert float(lt["maxVerticalSupportDistance"]) == pytest.approx(vd, abs=1e-6)
    for side in ("left", "right"):
        assert not bool(lt[side]["valid"]) and "8" in lt[side]["reason"]
    assert max(mvec(r["out"]["Abar_side1"])) == 0.0 and max(mvec(r["out"]["Abar_side2"])) == 0.0


def test_lateral_path_not_considered_when_terrain_contributes(eng):
    # Crest of a 12 m ridge at x=150 dominates the top path; the wall top at x=200 is hidden below it.
    r = eng.run_case_3d(case(ridge_x_dem(150.0, 12.0), [wall(200, 190, 200, 210, 6.0)]))
    lt = r["geom"]["lateral"]
    assert not bool(lt["considered"]) and "elevated ground" in lt["reason"]
    assert max(mvec(r["out"]["Abar_side1"])) == 0.0


def test_thick_building_multi_edge_top_and_lateral(eng):
    # 40 m x 20 m building, top 8 m, centred on the line: top path has e = 40 m (cap 25 dB).
    r = eng.run_case_3d(case(flat_dem(), [building(180, 220, 190, 210, 8.0)]))
    g = r["geom"]
    dss, dsr = math.hypot(80, 8 - S_Z), math.hypot(80, 8 - R_Z)
    assert float(g["e"]) == pytest.approx(40.0, abs=1e-6)
    assert float(g["dss"]) == pytest.approx(dss, abs=1e-6)
    assert float(g["z"]) == pytest.approx(dss + dsr + 40.0 - D, abs=1e-6)
    # lateral: vertices (180, +-10) and (220, +-10) -> path S, (u1, 10), (u2, 10), R
    u1 = (80 * 200 + 0.0) / D + 0.0                     # rel = (80, 10, dz), dz = LOS height drop; computed below
    # exact plane intersection height at x: t = S_z + (x-100)*(R_z-S_z)/200 (the lateral plane contains the LOS)
    def uv(x):
        t = S_Z + (x - 100) * (R_Z - S_Z) / 200.0
        rel = (x - 100.0, 10.0, t - S_Z)
        return (rel[0] * 200.0 + rel[2] * (R_Z - S_Z)) / D, 10.0
    (ua, _), (ub, _) = uv(180.0), uv(220.0)
    dss_l, dsr_l = math.hypot(ua, 10), math.hypot(D - ub, 10)
    e_l = math.hypot(ub - ua, 0.0)
    z_l = dss_l + dsr_l + e_l - D
    left = g["lateral"]["left"]
    assert bool(left["valid"]) and float(left["e"]) == pytest.approx(e_l, abs=1e-6)
    assert float(left["z"]) == pytest.approx(z_l, abs=1e-6)
    # caps: the top path uses 25 dB (multiple diffraction)
    assert max(mvec(r["out"]["Dz_top"])) <= 25.0 + 1e-9


def test_wall_that_does_not_block_has_no_lateral_path(eng):
    # Top 1 m is below the line of sight (1.75 m at mid-path): clear LOS, nothing to go around.
    r = eng.run_case_3d(case(flat_dem(), [wall(200, 190, 200, 210, 1.0)]))
    lt = r["geom"]["lateral"]
    assert not bool(lt["considered"])
    assert r["geom"]["kind"] == "clear_crest"
    assert max(mvec(r["out"]["Abar_side1"])) == 0.0


def test_wall_not_crossing_the_line_is_ignored(eng):
    base = eng.run_case_3d(case(flat_dem(), []))
    off = eng.run_case_3d(case(flat_dem(), [wall(200, 230, 200, 260, 10.0)]))     # entirely beside the path
    assert mvec(off["out"]["Lp"]) == pytest.approx(mvec(base["out"]["Lp"]), abs=1e-9)


def test_receiver_inside_building_is_invalid(eng):
    c = case(flat_dem(), [building(280, 320, 190, 210, 8.0)])
    r = eng.run_case_3d(c)
    assert not bool(r["valid"]) and "inside" in r["reason"]


def test_paths_are_returned_for_display(eng):
    r = eng.run_case_3d(case(flat_dem(), [wall(200, 190, 200, 210, 5.0)]))
    p = r["paths"]
    top = [list(row) for row in p["top"]]
    assert top[0] == [100.0, 200.0, 2.0] and top[-1] == [300.0, 200.0, 1.5]
    assert top[1][0] == pytest.approx(200.0) and top[1][2] == pytest.approx(5.0)         # edge on the wall top
    assert [list(row) for row in p["left"]][1][1] == pytest.approx(210.0)
    assert [list(row) for row in p["right"]][1][1] == pytest.approx(190.0)


def test_field_with_obstacles_shadow_and_lateral_codes(eng):
    c = dict(
        Lw=matlab.double([100.0] * 8), G={"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
        atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325}, dem=flat_dem(),
        source={"x": 100.0, "y": 200.0, "h": 2.0}, hr=1.5,
        grid={"x": matlab.double([300.0]), "y": matlab.double([200.0, 280.0, 120.0])},
        obstacles=[wall(200, 190, 200, 210, 5.0)])
    f = eng.run_field_3d(c)
    kinds = mvec(f["kind"])
    lat = mvec(f["lateralPaths"])
    assert kinds[0] == 1.0 and lat[0] == 3.0          # behind the wall: top + both lateral paths
    assert kinds[1] == 0.0 and lat[1] == 0.0          # y = 280: the line passes clear of the wall
    lp = [list(r) for r in f["Lp"]]
    assert lp[0][4] < lp[1][4]                        # 1 kHz is lower in the wall shadow
