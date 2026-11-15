"""GROUP 1 analytic geometry tests (2D vertical plane), ISO 9613-2:2024 cl. 7.4.1.

Expected paths are constructed by hand from the geometry (Pythagoras), never
from the edges returned by the solver. Formula (22): z = dss + dsr + e - d.
Formula (23): clear line of sight with real crests -> z = max(z_n) < 0.
"""
import math

import matlab
import pytest

from conftest import mvec


def prof(xs, zs):
    return matlab.double(xs), matlab.double(zs)


def run(eng, xs, zs, S, R):
    return eng.nb_geom2d(matlab.double(xs), matlab.double(zs), matlab.double(S), matlab.double(R))


def test_flat_terrain_makes_no_edge(eng):
    # Many collinear vertices on flat ground, LOS clear: no edge may be manufactured.
    xs = [float(x) for x in range(0, 201, 10)]
    g = run(eng, xs, [0.0] * len(xs), [0.0, 2.0], [200.0, 1.5])
    assert g["kind"] == "none"
    assert len(g["z"]) == 0 if hasattr(g["z"], "__len__") else False


def test_constant_slope_makes_no_edge(eng):
    xs = [float(x) for x in range(0, 201, 20)]
    zs = [0.1 * x for x in xs]
    g = run(eng, xs, zs, [0.0, 2.0], [200.0, 21.5])
    assert g["kind"] == "none"


def test_single_ridge_blocks_and_z_matches_hand_value(eng):
    # Triangular ridge, crest (100, 10). S=(0,2), R=(200,1.5).
    xs, zs = [0.0, 100.0, 200.0], [0.0, 10.0, 0.0]
    g = run(eng, xs, zs, [0.0, 2.0], [200.0, 1.5])
    assert g["kind"] == "blocked"
    dss = math.hypot(100, 8)
    dsr = math.hypot(100, 8.5)
    d = math.hypot(200, 0.5)
    assert float(g["dss"]) == pytest.approx(dss, abs=1e-9)
    assert float(g["dsr"]) == pytest.approx(dsr, abs=1e-9)
    assert float(g["e"]) == 0.0
    assert float(g["z"]) == pytest.approx(dss + dsr - d, abs=1e-9)
    assert float(g["z"]) > 0


def test_two_ridges_taut_string_and_e(eng):
    # Crests (80,10) and (120,10); S=(0,2), R=(200,2) -> hull S, E1, E2, R.
    xs = [0.0, 80.0, 120.0, 200.0]
    zs = [0.0, 10.0, 10.0, 0.0]
    g = run(eng, xs, zs, [0.0, 2.0], [200.0, 2.0])
    assert g["kind"] == "blocked"
    dss = math.hypot(80, 8)
    e = 40.0
    assert float(g["dss"]) == pytest.approx(dss, abs=1e-9)
    assert float(g["dsr"]) == pytest.approx(dss, abs=1e-9)
    assert float(g["e"]) == pytest.approx(e, abs=1e-9)
    assert float(g["z"]) == pytest.approx(2 * dss + e - 200.0, abs=1e-9)


def test_lower_second_ridge_is_not_on_the_taut_string(eng):
    # Second crest (150, 3) is hidden below the line E1 -> R and must not be an edge.
    xs = [0.0, 100.0, 150.0, 200.0]
    zs = [0.0, 10.0, 3.0, 0.0]
    g = run(eng, xs, zs, [0.0, 2.0], [200.0, 1.5])
    edges = g["edges"]
    assert len(edges) == 1 and edges[0][0] == pytest.approx(100.0)


def test_clear_los_over_low_crest_gives_negative_z(eng):
    # Crest (100, 1) well below S=(0,5), R=(200,5): z_n = |SE|+|ER|-d < 0.
    xs, zs = [0.0, 100.0, 200.0], [0.0, 1.0, 0.0]
    g = run(eng, xs, zs, [0.0, 5.0], [200.0, 5.0])
    assert g["kind"] == "clear_crest"
    zn = -(2 * math.hypot(100, 4) - 200.0)     # negative sign: LOS passes above the edge
    assert float(g["z"]) == pytest.approx(zn, abs=1e-9)
    assert float(g["z"]) < 0


def test_clear_los_uses_the_largest_zn_of_several_crests(eng):
    # Crests (60,2) and (140,4) under S=(0,6), R=(200,6). The less negative z_n wins.
    xs, zs = [0.0, 60.0, 100.0, 140.0, 200.0], [0.0, 2.0, 0.0, 4.0, 0.0]
    g = run(eng, xs, zs, [0.0, 6.0], [200.0, 6.0])
    z1 = -(math.hypot(60, 4) + math.hypot(140, 4) - 200.0)
    z2 = -(math.hypot(140, 2) + math.hypot(60, 2) - 200.0)
    assert float(g["z"]) == pytest.approx(max(z1, z2), abs=1e-9)


def test_heights_are_relative_to_local_ground(eng):
    xs, zs = [0.0, 100.0, 200.0], [5.0, 5.0, 8.0]
    g = run(eng, xs, zs, [0.0, 7.0], [200.0, 9.5])
    assert float(g["hs"]) == pytest.approx(2.0)
    assert float(g["hr"]) == pytest.approx(1.5)
    assert float(g["dh"]) == pytest.approx(3.0)


@pytest.mark.parametrize(
    "S,R",
    [([0.0, -1.0], [200.0, 1.5]),      # source underground
     ([-5.0, 2.0], [200.0, 1.5]),      # outside domain
     ([200.0, 2.0], [0.0, 1.5])],      # reversed order
)
def test_invalid_geometry_is_rejected(eng, S, R):
    with pytest.raises(matlab.engine.MatlabExecutionError):
        run(eng, [0.0, 100.0, 200.0], [0.0, 0.0, 0.0], S, R)


def test_run_case_2d_ridge_adds_barrier_attenuation(eng):
    base = dict(
        Lw=matlab.double([100.0] * 8),
        G={"Gs": 0.0, "Gm": 0.0, "Gr": 0.0},
        atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325},
        source={"x": 0.0, "h": 2.0}, receiver={"x": 200.0, "h": 1.5},
    )
    flat = eng.run_case_2d(dict(base, terrain={"x": matlab.double([0.0, 200.0]), "z": matlab.double([0.0, 0.0])}))
    ridge = eng.run_case_2d(dict(base, terrain={"x": matlab.double([0.0, 100.0, 200.0]), "z": matlab.double([0.0, 10.0, 0.0])}))
    assert max(mvec(flat["Abar"])) == 0.0
    ab = mvec(ridge["Abar"])
    assert ab[4] > 5.0                       # 1 kHz: a 10 m ridge must screen strongly
    assert max(ab) <= 20.0 + 1e-9            # single-edge cap
    # lower levels with the ridge, in every band where Abar > 0
    lf, lr = mvec(flat["Lp"]), mvec(ridge["Lp"])
    assert all(r <= f + 1e-9 for r, f in zip(lr, lf))
