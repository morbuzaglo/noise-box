"""GROUP 1 analytic tests of the MATLAB core, ISO 9613-2:2024.

Every expected value is either hand-derived from the printed equation (source
cited per test, PDF = standard_iso_9613-2_2024.pdf page) or follows from a
mathematical limit. None is computed by the MATLAB function under test.
Tests call the real MATLAB production functions through the Engine.
"""
import math

import matlab.engine
import pytest

from conftest import mvec

F_NOM = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


def test_adiv_100m(eng):
    # Formula (8), printed p. 8: 20 lg(100/1) + 11 = 51 exactly.
    assert eng.nb_adiv(100.0) == pytest.approx(51.0, abs=1e-12)


def test_adiv_rejects_zero_distance(eng):
    with pytest.raises(matlab.engine.MatlabExecutionError):
        eng.nb_adiv(0.0)


def test_energy_sum_two_equal_levels(eng):
    # 10 lg(2 * 10^6) = 60 + 10 lg 2 = 63.0103
    assert eng.nb_energy_sum(matlab.double([60.0, 60.0])) == pytest.approx(60 + 10 * math.log10(2), abs=1e-9)


def test_energy_sum_nan_is_not_dropped(eng):
    v = eng.nb_energy_sum(matlab.double([60.0, float("nan")]))
    assert math.isnan(v)


def test_exact_band_centres(eng):
    # cl. 7.2, printed p. 9: exact base-10 centre frequencies 1000*10^(0.3 n)
    fe = mvec(eng.getfield(eng.nb_bands(), "fexact"))
    exp = [1000 * 10 ** (0.3 * n) for n in range(-4, 4)]
    assert fe == pytest.approx(exp, rel=1e-12)


def test_agr_hard_ground_far_limit(eng):
    # Table 3 with G=0: As = Ar = -1.5 in every band; Am = -3q, q -> 1 as dp -> inf;
    # Kgeo -> 1, so Formula (11) gives Agr -> A' = -1.5 - 1.5 - 3 = -6 dB.
    r = eng.nb_agr(0.0, 0.0, 0.0, 1.0, 1.0, 1e7)
    agr = mvec(r["Agr"])
    assert agr == pytest.approx([-6.0] * 8, abs=1e-3)


def test_agr_porous_high_bands_zero(eng):
    # Table 3, 2000-8000 Hz: -1.5(1-G) = 0 for G=1 (As, Ar); Am = -3q(1-Gm) = 0 for Gm=1
    # => A' = 0 => Agr = -10 lg(1 + 0) = 0 in those bands.
    r = eng.nb_agr(1.0, 1.0, 1.0, 2.0, 1.5, 200.0)
    agr = mvec(r["Agr"])
    assert agr[5:] == pytest.approx([0.0] * 3, abs=1e-12)


def test_agr_63hz_uses_minus_1p5(eng):
    # Table 3, 63 Hz: As = Ar = -1.5 for any G.
    r = eng.nb_agr(1.0, 1.0, 1.0, 2.0, 1.5, 200.0)
    assert mvec(r["As"])[0] == pytest.approx(-1.5, abs=1e-12)
    assert mvec(r["Ar"])[0] == pytest.approx(-1.5, abs=1e-12)


def test_agr_can_be_negative_and_is_not_clamped(eng):
    r = eng.nb_agr(0.0, 0.0, 0.0, 2.0, 1.5, 200.0)
    assert min(mvec(r["Agr"])) < 0


def test_agr_kgeo_formula(eng):
    # Formula (13): (dp^2 + (hs-hr)^2) / (dp^2 + (hs+hr)^2)
    dp, hs, hr = 200.0, 2.0, 1.5
    r = eng.nb_agr(1.0, 0.5, 1.0, hs, hr, dp)
    exp = (dp**2 + (hs - hr) ** 2) / (dp**2 + (hs + hr) ** 2)
    assert float(r["Kgeo"]) == pytest.approx(exp, rel=1e-12)


def test_agr_rejects_g_out_of_range(eng):
    with pytest.raises(matlab.engine.MatlabExecutionError):
        eng.nb_agr(1.2, 0.5, 1.0, 2.0, 1.5, 200.0)


def _dz_expected_2024(z, lam, kmet=1.0, c3=1.0, c2=20.0):
    # Formula (18), printed p. 16: 10 lg[1 + (2 + (C2/lam) C3 z) Kmet]
    return 10 * math.log10(1 + (2 + (c2 / lam) * c3 * z) * kmet)


def test_dz_2024_single_edge_1khz(eng):
    # tiny distances make Kmet ~ 1 so only Formula (18) is exercised
    r = eng.nb_dz(0.5, 1e-9, 1e-9, 1e-9, 0.0, "iso2024", False)
    dz = mvec(r["Dz"])
    lam = 340 / 1000
    assert dz[4] == pytest.approx(_dz_expected_2024(0.5, lam), abs=1e-6)


def test_dz_2024_is_continuous_and_real_just_above_zmin(eng):
    # At z = zmin the bracket in (18) equals 1 for ANY Kmet, so Dz -> 0 dB and must stay real.
    lam = 0.34
    zmin = -2 * lam / 20
    for dss, dsr, d in [(1e-9, 1e-9, 1e-9), (50.0, 60.0, 100.0), (500.0, 600.0, 1000.0)]:
        r = eng.nb_dz(zmin + 1e-9, dss, dsr, d, 0.0, "iso2024", False)
        dz = mvec(r["Dz"])
        assert dz[4] == pytest.approx(0.0, abs=1e-6)


def test_dz_2024_never_negative_or_complex_for_negative_z(eng):
    for z in [-0.0001, -0.005, -0.01, -0.0169]:
        dz = mvec(eng.nb_dz(z, 100.0, 120.0, 200.0, 0.0, "iso2024", False)["Dz"])
        assert all(v >= 0.0 for v in dz)


def test_dz_2024_zero_at_or_below_zmin(eng):
    # Formula (19): zmin = -2 lam / (C2 C3); Dz = 0 for z <= zmin
    lam = 0.34
    zmin = -2 * lam / 20
    r = eng.nb_dz(zmin - 1e-6, 10.0, 10.0, 20.0, 0.0, "iso2024", False)
    assert mvec(r["Dz"])[4] == 0.0


def test_dz_2024_cap_20db_single_and_25db_multiple(eng):
    single = mvec(eng.nb_dz(1e4, 1.0, 1.0, 1.0, 0.0, "iso2024", False)["Dz"])
    multi = mvec(eng.nb_dz(1e4, 1.0, 1.0, 1.0, 5.0, "iso2024", False)["Dz"])
    assert max(single) == pytest.approx(20.0, abs=1e-12)
    assert max(multi) == pytest.approx(25.0, abs=1e-12)


def test_dz_lateral_has_no_meteo_factor(eng):
    # "For lateral diffraction ... Kmet = 1" (printed p. 16)
    r = eng.nb_dz(0.5, 500.0, 500.0, 1000.0, 0.0, "iso2024", True)
    assert all(k == 1.0 for k in mvec(r["Kmet"]))


def test_dz_c3_formula_multiple_edges(eng):
    # Formula (20) at 1 kHz, e = 5 m
    lam, e = 0.34, 5.0
    t = (5 * lam / e) ** 2
    c3 = (1 + t) / (1 / 3 + t)
    r = eng.nb_dz(0.5, 1e-9, 1e-9, 1e-9, e, "iso2024", False)
    assert mvec(r["C3"])[4] == pytest.approx(c3, rel=1e-12)


def test_draft_dz_formula_positive_z(eng):
    # DAmd 1 eq. (18): 10 lg[3 + (C2/lam) C3 z Kmet], screenshot of the draft
    r = eng.nb_dz(0.5, 1e-9, 1e-9, 1e-9, 0.0, "draft2026", False)
    lam = 0.34
    exp = 10 * math.log10(3 + (20 / lam) * 0.5)
    assert mvec(r["Dz"])[4] == pytest.approx(exp, abs=1e-6)


def test_draft_dz_continuous_at_zmin(eng):
    # 3 + (C2/lam) z at z = zmin = -2 lam/C2 is 3 - 2 = 1 -> 0 dB (continuity)
    lam = 0.34
    zmin = -2 * lam / 20
    r = eng.nb_dz(zmin + 1e-9, 1e-9, 1e-9, 1e-9, 0.0, "draft2026", False)
    assert mvec(r["Dz"])[4] == pytest.approx(0.0, abs=1e-6)


def test_draft_kmet_is_one_for_nonpositive_z(eng):
    r = eng.nb_dz(-0.01, 100.0, 100.0, 200.0, 0.0, "draft2026", False)
    assert all(k == 1.0 for k in mvec(r["Kmet"]))


def test_draft_kmet_positive_z_formula(eng):
    dss, dsr, d, z = 100.0, 120.0, 200.0, 0.4
    r = eng.nb_dz(z, dss, dsr, d, 0.0, "draft2026", False)
    exp = math.exp(-(1 / 2000) * math.sqrt(dss * dsr * d / (2 * z)))
    assert mvec(r["Kmet"])[4] == pytest.approx(exp, rel=1e-12)


def test_modes_differ(eng):
    a = mvec(eng.nb_dz(0.5, 50.0, 50.0, 100.0, 0.0, "iso2024", False)["Dz"])
    b = mvec(eng.nb_dz(0.5, 50.0, 50.0, 100.0, 0.0, "draft2026", False)["Dz"])
    assert a != b


def test_abar_two_equal_paths(eng):
    # Formula (25): -10 lg(2 * 10^-1) = 10 - 3.0103
    ten = matlab.double([10.0] * 8)
    zero_agr = matlab.double([0.0] * 8)
    r = eng.nb_abar(ten, ten, matlab.double([]), zero_agr)
    assert mvec(r["Abar"])[0] == pytest.approx(10 - 10 * math.log10(2), abs=1e-9)


def test_abar_top_subtracts_positive_agr_only(eng):
    # Formulae (16)/(17)
    dz = matlab.double([10.0] * 8)
    agr = matlab.double([3.0, -2.0, 0.0, 3.0, -2.0, 0.0, 3.0, -2.0])
    r = eng.nb_abar(dz, matlab.double([]), matlab.double([]), agr)
    got = mvec(r["Abar"])
    assert got == pytest.approx([7.0, 10.0, 10.0, 7.0, 10.0, 10.0, 7.0, 10.0], abs=1e-9)


def test_abar_irrelevant_paths_give_zero(eng):
    r = eng.nb_abar(matlab.double([]), matlab.double([]), matlab.double([]), matlab.double([0.0] * 8))
    assert mvec(r["Abar"]) == [0.0] * 8


def test_cmet_formulas(eng):
    # Formulae (31), (32), printed p. 24
    assert eng.nb_cmet(2.0, 1.0, 1.0, 20.0) == 0.0          # dp <= 10(hs+hr)
    assert eng.nb_cmet(2.0, 1.0, 1.0, 40.0) == pytest.approx(2.0 * (1 - 20 / 40), abs=1e-12)


def _case(**kw):
    c = dict(
        Lw=matlab.double([100.0] * 8),
        hs=2.0, hr=1.5, dp=100.0,
        G={"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
        atm={"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325},
    )
    c.update(kw)
    return c


def test_run_case_formula_3_and_5(eng):
    out = eng.run_acoustic_case(_case())
    lw = 100.0
    a = [mvec(out[k]) for k in ("Adiv", "Aatm", "Agr", "Abar", "Amisc")]
    lp = mvec(out["Lp"])
    for i in range(8):
        total = sum(x[i] for x in a)
        assert lp[i] == pytest.approx(lw - total, abs=1e-9)          # Formula (3) with Dc = 0
        assert mvec(out["Atotal"])[i] == pytest.approx(total, abs=1e-9)  # Formula (5)


def test_run_case_broadband_is_energy_sum_not_mean(eng):
    out = eng.run_acoustic_case(_case())
    lp = mvec(out["Lp"])
    exp = 10 * math.log10(sum(10 ** (v / 10) for v in lp))
    assert float(out["Lp_broadband"]) == pytest.approx(exp, abs=1e-9)
    assert float(out["Lp_broadband"]) > max(lp)


def test_run_case_no_cmet_by_default(eng):
    out = eng.run_acoustic_case(_case())
    assert float(out["Cmet"]) == 0.0
    assert out["Lp_longterm_applied"] is False


def test_run_case_reports_unimplemented(eng):
    out = eng.run_acoustic_case(_case())
    assert len(out["notImplemented"]) >= 2
