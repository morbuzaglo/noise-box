"""Compliance logic: one exceeded band must fail the point (brief, section on pass/fail map)."""
import math

import matlab
import pytest

from conftest import mvec

NAN = float("nan")


def comp(eng, Lp, LpA, bands, weighting="Z", overallA=NAN):
    lim = {"bands": matlab.double(bands), "weighting": weighting, "overallA": overallA}
    return eng.nb_compliance(matlab.double(Lp), matlab.double(LpA), lim)


def test_all_bands_below_limits_pass(eng):
    r = comp(eng, [[40.0] * 8], [[30.0] * 8], [45.0] * 8)
    assert r["status"][0] == "PASS" and float(r["code"]) == 1.0


def test_one_band_exceeding_fails_even_if_dba_would_pass(eng):
    lp = [40.0] * 8
    lp[3] = 46.0                                    # 500 Hz exceeds 45
    r = comp(eng, [lp], [[20.0] * 8], [45.0] * 8, overallA=60.0)   # overall dBA is far below its limit
    assert r["status"][0] == "FAIL"
    assert mvec(r["margin"])[3] == pytest.approx(1.0, abs=1e-12)
    assert int(r["worstBand"]) == 4                  # MATLAB index of 500 Hz
    assert float(r["worstMargin"]) == pytest.approx(1.0)


def test_exactly_at_limit_passes(eng):
    r = comp(eng, [[45.0] * 8], [[0.0] * 8], [45.0] * 8)
    assert r["status"][0] == "PASS"


def test_bands_without_limit_are_ignored_but_reported(eng):
    lim = [NAN] * 8
    lim[4] = 40.0
    lp = [80.0] * 8
    lp[4] = 39.0
    r = comp(eng, [lp], [[0.0] * 8], lim)
    assert r["status"][0] == "PASS"                 # other bands have no limit


def test_no_limits_is_not_pass(eng):
    r = comp(eng, [[40.0] * 8], [[30.0] * 8], [NAN] * 8)
    assert r["status"][0] == "NO LIMITS"


def test_nan_prediction_is_no_data_not_pass_or_fail(eng):
    lp = [40.0] * 8
    lp[2] = NAN
    r = comp(eng, [lp], [[30.0] * 8], [45.0] * 8)
    assert r["status"][0] == "NO DATA"


def test_failing_band_beats_missing_band(eng):
    lp = [40.0] * 8
    lp[2] = NAN
    lp[5] = 50.0
    r = comp(eng, [lp], [[30.0] * 8], [45.0] * 8)
    assert r["status"][0] == "FAIL"


def test_a_weighted_limits_use_a_weighted_bands(eng):
    lp, lpa = [[60.0] * 8], [[44.0] * 8]
    assert comp(eng, lp, lpa, [45.0] * 8, "A")["status"][0] == "PASS"
    assert comp(eng, lp, lpa, [45.0] * 8, "Z")["status"][0] == "FAIL"


def test_overall_dba_limit_is_separate(eng):
    lpa = [[40.0] * 8]
    bb = 10 * math.log10(8 * 10 ** 4.0)             # 49.03 dBA from eight 40 dB bands
    ok = comp(eng, [[30.0] * 8], lpa, [45.0] * 8, "Z", overallA=bb + 0.5)
    bad = comp(eng, [[30.0] * 8], lpa, [45.0] * 8, "Z", overallA=bb - 0.5)
    assert ok["status"][0] == "PASS" and bad["status"][0] == "FAIL"
    assert float(bad["overallMargin"]) == pytest.approx(0.5, abs=1e-9)


def test_vectorised_over_points(eng):
    lp = [[40.0] * 8, [50.0] * 8, [40.0] * 8]
    lp[2][0] = NAN
    r = comp(eng, lp, [[30.0] * 8] * 3, [45.0] * 8)
    assert list(r["status"]) == ["PASS", "FAIL", "NO DATA"]
