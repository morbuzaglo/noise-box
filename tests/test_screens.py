"""Feature 1 (enclosure) and Feature 2 (transmissive screen). Expected values by hand from the formulas
stated in the function headers; geometry as in test_obstacles3d."""
import math

import matlab
import pytest

from conftest import mvec
from test_obstacles3d import F, abar_expected, case, dz2024, flat_dem, wall

D = math.hypot(200.0, 0.5)


# ---------------------------------------------------------------- materials
def mass_law(m, f):
    return 20 * math.log10(f * m) - 20 * math.log10(415 / math.pi)


def test_mass_law_normal_incidence_values(eng):
    tl = mvec(eng.nb_material("massLaw", 10.0, matlab.double([float(f) for f in F]), "normal"))
    assert tl[4] == pytest.approx(80 - 42.42, abs=0.01)                 # 20 lg(1000*10) - 42.42 = 37.58
    assert tl == pytest.approx([max(mass_law(10.0, f), 0.0) for f in F], abs=1e-9)


def test_mass_law_slope_is_6db_per_octave_and_field_is_5db_lower(eng):
    f = matlab.double([1000.0, 2000.0])
    n = mvec(eng.nb_material("massLaw", 5.0, f, "normal"))
    fl = mvec(eng.nb_material("massLaw", 5.0, f, "field"))
    assert n[1] - n[0] == pytest.approx(20 * math.log10(2), abs=1e-9)
    assert [a - b for a, b in zip(n, fl)] == pytest.approx([5.0, 5.0], abs=1e-9)


def test_surface_mass_from_volume_density_only_for_solid_layers(eng):
    assert eng.nb_material("surfaceMass", 800.0, 0.02, True) == pytest.approx(16.0)
    with pytest.raises(matlab.engine.MatlabExecutionError):
        eng.nb_material("surfaceMass", 800.0, 0.02, False)        # not a homogeneous solid


def test_effective_tl_with_openings(eng):
    tl = matlab.double([30.0])
    assert eng.nb_material("effectiveTL", tl, 0.0) == pytest.approx(30.0)
    assert eng.nb_material("effectiveTL", tl, 1.0) == pytest.approx(0.0)
    assert eng.nb_material("effectiveTL", tl, 0.5) == pytest.approx(-10 * math.log10(0.5 + 0.5e-3), abs=1e-9)


def test_resolve_prefers_measured_tl_and_warns_below_10kg(eng):
    r = eng.nb_material("resolve", {"surface_mass": 0.3, "TL": matlab.double([5.0] * 8)})
    assert r["source"] == "measured" and mvec(r["TL"]) == [5.0] * 8
    assert any("10 kg/m^2" in w for w in r["warnings"])
    r2 = eng.nb_material("resolve", {"surface_mass": 0.3})
    assert r2["source"].startswith("mass-law") and r2["confidence"] == "rough estimate"
    with pytest.raises(matlab.engine.MatlabExecutionError):
        eng.nb_material("resolve", {"openness": 0.1})              # neither TL nor mass


def test_resolve_rejects_volume_density_for_fabric(eng):
    with pytest.raises(matlab.engine.MatlabExecutionError):
        eng.nb_material("resolve", {"volume_density": 300.0, "thickness": 0.002, "solid": False})


# ---------------------------------------------------------------- enclosure
def enc_expected(lw_in, S, A, tl, s_open):
    out = []
    for lw, t in zip(lw_in, tl):
        tleff = -10 * math.log10((s_open + (S - s_open) * 10 ** (-t / 10)) / S)
        out.append(lw + 10 * math.log10(4 / A) - tleff + 10 * math.log10(S) - 6)
    return out


def test_enclosure_formula_and_reduction(eng):
    lw = [90.0, 95.0, 100.0, 100.0, 98.0, 95.0, 90.0, 85.0]
    tl = [10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0]
    enc = {"S_total": 6.0, "A_in": 8.0, "mat": {"TL": matlab.double(tl)}}
    r = eng.nb_enclosure(matlab.double(lw), enc)
    assert mvec(r["Lw_out"]) == pytest.approx(enc_expected(lw, 6.0, 8.0, tl, 0.0), abs=1e-9)
    assert all(v > 0 for v in mvec(r["reduction"]))
    assert any("diffuse" in w for w in r["warnings"])


def test_enclosure_openings_limit_the_reduction(eng):
    lw = [100.0] * 8
    tl = [60.0] * 8                                   # very good panel
    r0 = eng.nb_enclosure(matlab.double(lw), {"S_total": 6.0, "A_in": 8.0, "mat": {"TL": matlab.double(tl)}})
    r1 = eng.nb_enclosure(matlab.double(lw), {"S_total": 6.0, "A_in": 8.0, "S_open": 0.06, "mat": {"TL": matlab.double(tl)}})
    assert mvec(r1["Lw_out"]) == pytest.approx(enc_expected(lw, 6.0, 8.0, tl, 0.06), abs=1e-9)
    assert mvec(r1["TLeff"])[0] == pytest.approx(-10 * math.log10(0.01 + 0.99e-6), abs=1e-6)   # ~ 20 dB (1 % open)
    assert min(mvec(r1["Lw_out"])) > max(mvec(r0["Lw_out"]))


def test_enclosure_with_too_little_absorption_is_flagged_not_clamped(eng):
    r = eng.nb_enclosure(matlab.double([90.0] * 8), {"S_total": 6.0, "A_in": 0.05, "mat": {"TL": matlab.double([3.0] * 8)}})
    assert any(bool(v) for v in mvec(r["notApplicableBands"]))
    assert max(mvec(r["Lw_out"])) > 90.0                # reported as is


def test_enclosure_changes_the_prediction_through_the_chain(eng):
    c = dict(Lw=matlab.double([100.0] * 8), hs=2.0, hr=1.5, dp=100.0,
             G={"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}, atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325})
    bare = eng.run_acoustic_case(c)
    enc = {"S_total": 6.0, "A_in": 8.0, "mat": {"TL": matlab.double([20.0] * 8)}}
    boxed = eng.run_acoustic_case(dict(c, enclosure=enc))
    expected = enc_expected([100.0] * 8, 6.0, 8.0, [20.0] * 8, 0.0)
    assert mvec(boxed["Lw"]) == pytest.approx(expected, abs=1e-9)
    assert mvec(boxed["Lp"]) == pytest.approx([a - b + e - 100.0 for a, b, e in zip(mvec(bare["Lp"]), [0] * 8, expected)], abs=1e-9)


# ---------------------------------------------------------------- screens
def screen_wall(**mat):
    w = wall(200, 190, 200, 210, 5.0)
    w["mat"] = mat
    return w


def test_screen_energy_identity_and_opaque_abar_matches_iso_run(eng):
    tl = [15.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0]
    plain = eng.run_case_3d(case(flat_dem(), [wall(200, 190, 200, 210, 5.0)]))
    scr = eng.run_case_3d(case(flat_dem(), [screen_wall(TL=matlab.double(tl))]))
    s = scr["out"]["screen"]
    a_op = mvec(s["Abar_opaque"])
    assert a_op == pytest.approx(mvec(plain["out"]["Abar"]), abs=1e-9)          # same ISO opaque barrier
    # Where the opaque barrier gives no insertion loss (A_bar = 0, e.g. D_z - A_gr <= 0 at 250 Hz here),
    # no transmission term is added: the fabric cannot make the level exceed the free field.
    a_eff = [(-10 * math.log10(10 ** (-a / 10) + 10 ** (-t / 10))) if a > 0 else 0.0 for a, t in zip(a_op, tl)]
    assert a_op[2] == 0.0 and a_op[4] > 0.0                                      # both branches are exercised
    assert mvec(s["A_eff"]) == pytest.approx(a_eff, abs=1e-9)
    assert all(e <= a + 1e-12 for e, a in zip(mvec(s["A_eff"]), a_op))        # transmission can only reduce IL
    # energy sum of the two paths equals the total level
    ld, lt = mvec(s["L_diffracted"]), mvec(s["L_transmitted"])
    tot = [10 * math.log10(10 ** (a / 10) + 10 ** (b / 10)) for a, b in zip(ld, lt)]
    free = [100.0 - (adv + atm + agr) for adv, atm, agr in zip(mvec(scr["out"]["Adiv"]), mvec(scr["out"]["Aatm"]), mvec(scr["out"]["Agr"]))]
    assert mvec(scr["out"]["Lp"]) == pytest.approx([f - a for f, a in zip(free, a_eff)], abs=1e-9)
    lp = mvec(scr["out"]["Lp"])
    for i in range(8):
        if a_op[i] > 0:                                     # identity holds where the screen contributes
            assert tot[i] == pytest.approx(lp[i], abs=1e-9)
        else:                                               # no screening in this band: level stays at free field
            assert lp[i] == pytest.approx(free[i], abs=1e-9)


def test_very_high_tl_recovers_the_opaque_barrier(eng):
    plain = eng.run_case_3d(case(flat_dem(), [wall(200, 190, 200, 210, 5.0)]))
    scr = eng.run_case_3d(case(flat_dem(), [screen_wall(TL=matlab.double([80.0] * 8))]))
    assert mvec(scr["out"]["Lp"]) == pytest.approx(mvec(plain["out"]["Lp"]), abs=1e-4)
    assert bool(scr["out"]["screen"]["opaqueAssumptionOK"])


def test_low_tl_breaks_the_opaque_assumption_and_flags_it(eng):
    scr = eng.run_case_3d(case(flat_dem(), [screen_wall(TL=matlab.double([6.0] * 8))]))
    assert not bool(scr["out"]["screen"]["opaqueAssumptionOK"])
    assert "NOT prescribed by ISO" in scr["out"]["screen"]["method"]


def test_light_fabric_uses_rough_mass_law_and_warns(eng):
    scr = eng.run_case_3d(case(flat_dem(), [screen_wall(surface_mass=0.4)]))
    info = scr["out"]["screen"]["info"]
    assert any("10 kg/m^2" in w for w in info["warnings"]) or "10 kg/m^2" in str(info["warnings"])
    tl = mvec(scr["out"]["screen"]["TL"])
    assert tl == pytest.approx([max(mass_law(0.4, f), 0.0) for f in F], abs=1e-9)


def test_openness_reduces_effective_tl(eng):
    solid = eng.run_case_3d(case(flat_dem(), [screen_wall(TL=matlab.double([30.0] * 8))]))
    porous = eng.run_case_3d(case(flat_dem(), [screen_wall(TL=matlab.double([30.0] * 8), openness=0.2)]))
    assert mvec(porous["out"]["screen"]["TL"])[0] == pytest.approx(-10 * math.log10(0.2 + 0.8e-3), abs=1e-9)
    assert max(mvec(porous["out"]["Abar"])) < max(mvec(solid["out"]["Abar"]))


def test_no_material_means_opaque_no_screen_struct(eng):
    r = eng.run_case_3d(case(flat_dem(), [wall(200, 190, 200, 210, 5.0)]))
    assert not bool(r["out"]["screenApplied"])


def test_two_fabrics_in_series_add_their_tl(eng):
    w1 = screen_wall(TL=matlab.double([10.0] * 8))
    w2 = wall(250, 190, 250, 210, 5.0)
    w2["mat"] = {"TL": matlab.double([12.0] * 8)}
    r = eng.run_case_3d(case(flat_dem(), [w1, w2]))
    assert mvec(r["out"]["screen"]["TL"]) == pytest.approx([22.0] * 8, abs=1e-9)


def test_one_opaque_obstacle_in_series_disables_transmission(eng):
    w1 = screen_wall(TL=matlab.double([10.0] * 8))
    w2 = wall(250, 190, 250, 210, 5.0)                 # no material: opaque
    r = eng.run_case_3d(case(flat_dem(), [w1, w2]))
    assert not bool(r["out"]["screenApplied"])


# ---------------------------------------------------------------- gap and width criterion
def test_screen_hanging_above_the_line_of_sight_does_not_block(eng):
    base = eng.run_case_3d(case(flat_dem(), []))
    w = wall(200, 100, 200, 300, 6.0)
    w["gap"] = 3.0                                      # bottom at 3 m, LOS is 1.75 m at mid-path
    hang = eng.run_case_3d(case(flat_dem(), [w]))
    assert mvec(hang["out"]["Lp"]) == pytest.approx(mvec(base["out"]["Lp"]), abs=1e-9)


def test_gap_path_is_added_as_an_engineering_extension(eng):
    w = wall(200, 100, 200, 300, 5.0)                   # long: lateral paths neglected (factor 8)
    w["gap"] = 1.0                                      # bottom edge at 1 m; LOS 1.75 m is inside the fabric
    r = eng.run_case_3d(case(flat_dem(), [w]))
    g = r["geom"]
    assert bool(g["under"]["present"])
    zu = math.hypot(100, 1 - 2.0) + math.hypot(100, 1 - 1.5) - D
    assert float(g["under"]["z"]) == pytest.approx(zu, abs=1e-9)
    dss, dsr = math.hypot(100, 5 - 2.0), math.hypot(100, 5 - 1.5)
    ztop = dss + dsr - D
    agr = mvec(r["out"]["Agr"])
    exp = abar_expected(lambda f: dz2024(ztop, dss, dsr, D, 0.0, f, False),
                        [lambda f: dz2024(zu, math.hypot(100, -1.0), math.hypot(100, -0.5), D, 0.0, f, True)], agr)
    assert mvec(r["out"]["Abar"]) == pytest.approx(exp, abs=1e-6)
    # the under path leaks energy: A_bar is lower than for the same wall reaching the ground
    full = eng.run_case_3d(case(flat_dem(), [wall(200, 100, 200, 300, 5.0)]))
    assert all(a <= b + 1e-9 for a, b in zip(mvec(r["out"]["Abar"]), mvec(full["out"]["Abar"])))


def test_object_narrower_than_the_wavelength_does_not_screen_low_bands(eng):
    # 2 m wide wall: lambda = 340/f is 5.4 m (63 Hz) and 2.72 m (125 Hz) > 2 m, but 1.36 m at 250 Hz.
    r = eng.run_case_3d(case(flat_dem(), [wall(200, 199, 200, 201, 5.0)]))
    mask = [bool(v) for v in mvec(r["geom"]["objectWidthCriterion"])]
    assert mask == [False, False, True, True, True, True, True, True]
    ab = mvec(r["out"]["Abar"])
    wide = mvec(eng.run_case_3d(case(flat_dem(), [wall(200, 190, 200, 210, 5.0)]))["out"]["Abar"])
    assert wide[0] > 0.0 and wide[1] > 0.0                  # a 20 m wall does screen 63 and 125 Hz
    assert ab[0] == 0.0 and ab[1] == 0.0                    # the 2 m wall does not (width < lambda)
    assert ab[4] > 0.0                                      # but it still screens 1 kHz
