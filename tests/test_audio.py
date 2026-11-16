"""Audio pipeline: octave-band levels, calibration, background subtraction, L_W estimate.

Signals are synthetic with analytically known levels. The filter bank is a CUSTOM Butterworth
design, so tolerances come from its measured behaviour (stated per test), not from IEC 61260-1.
"""
import math

import matlab
import numpy as np
import pytest
from scipy.io import wavfile

from conftest import CORE, mvec

FS = 44100
BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
FEXACT = [1000 * 10 ** (0.3 * n) for n in range(-4, 4)]


def write(path, x):
    wavfile.write(str(path), FS, x.astype(np.float32))
    return str(path)


def tone(f, rms, seconds=10.0):
    t = np.arange(int(FS * seconds)) / FS
    return rms * math.sqrt(2) * np.sin(2 * math.pi * f * t)


def analyse(eng, path, start, stop, **extra):
    c = dict(file=path, start=float(start), stop=float(stop))
    c.update(extra)
    return eng.run_audio_analysis(c)


def test_tone_at_each_band_centre_reads_its_level(eng, tmp_path):
    # Butterworth band-pass has unity gain at its geometric centre: expect the tone level within 0.15 dB,
    # and every other band at least 30 dB lower (6th-order skirts).
    for k, fm in enumerate(FEXACT):
        p = write(tmp_path / f"t{k}.wav", tone(fm, 0.1))
        r = analyse(eng, p, 2.0, 9.0)
        L = mvec(r["L"])
        assert L[k] == pytest.approx(20 * math.log10(0.1), abs=0.15), (BANDS[k], L[k])
        others = [v for i, v in enumerate(L) if i != k and abs(i - k) >= 2]
        assert all(v < L[k] - 30 for v in others), (BANDS[k], L)


def test_uncalibrated_levels_are_flagged_relative(eng, tmp_path):
    p = write(tmp_path / "t.wav", tone(1000.0, 0.1))
    r = analyse(eng, p, 2.0, 9.0)
    assert not bool(r["absolute"])
    assert "UNCALIBRATED" in r["signal"]["unit"]


def test_white_noise_band_power_matches_the_bandwidth_fraction(eng, tmp_path):
    # White noise, sigma = 0.1: band power = sigma^2 * (f2-f1)/(fs/2). A 3rd-order Butterworth band-pass has
    # a noise bandwidth ~4.7 % above its 3 dB bandwidth (+0.2 dB), so allow 0.5 dB.
    rng = np.random.default_rng(1)
    x = 0.1 * rng.standard_normal(FS * 20)
    p = write(tmp_path / "n.wav", x)
    r = analyse(eng, p, 2.0, 19.0)
    L = mvec(r["L"])
    for k, fm in enumerate(FEXACT):
        f1, f2 = fm * 10 ** -0.15, fm * 10 ** 0.15
        expected = 20 * math.log10(0.1 * math.sqrt((f2 - f1) / (FS / 2)))
        assert L[k] == pytest.approx(expected, abs=0.5), (BANDS[k], L[k], expected)


def test_calibrator_recording_gives_absolute_levels(eng, tmp_path):
    cal = write(tmp_path / "cal.wav", tone(1000.0, 0.05, 6.0))          # 94 dB calibrator recorded at rms 0.05
    sig = write(tmp_path / "sig.wav", tone(1000.0, 0.10, 10.0))
    r = analyse(eng, sig, 2.0, 9.0, calibrator={"file": cal, "start": 1.0, "stop": 5.0, "level": 94.0, "freq": 1000.0})
    assert bool(r["absolute"])
    assert float(r["calibration"]["paPerUnit"]) == pytest.approx(20e-6 * 10 ** (94 / 20) / 0.05, rel=2e-3)
    assert mvec(r["L"])[4] == pytest.approx(94 + 20 * math.log10(0.10 / 0.05), abs=0.15)      # 100.02 dB re 20 uPa
    assert "re 20 uPa" in r["signal"]["unit"]


def test_direct_sensitivity_input(eng, tmp_path):
    sig = write(tmp_path / "sig.wav", tone(1000.0, 0.10, 10.0))
    r = analyse(eng, sig, 2.0, 9.0, paPerUnit=20.0)
    assert mvec(r["L"])[4] == pytest.approx(20 * math.log10(0.10 * 20.0 / 20e-6), abs=0.15)    # 100.0 dB


def test_noise_only_calibrator_is_rejected_or_warned(eng, tmp_path):
    rng = np.random.default_rng(2)
    bad = write(tmp_path / "badcal.wav", 0.1 * rng.standard_normal(FS * 6))
    sig = write(tmp_path / "sig.wav", tone(1000.0, 0.10))
    r = analyse(eng, sig, 2.0, 9.0, calibrator={"file": bad, "start": 1.0, "stop": 5.0, "level": 94.0, "freq": 1000.0})
    assert any("dominated" in w for w in r["calibration"]["warnings"])


def test_short_interval_and_missing_preroll_are_warned(eng, tmp_path):
    p = write(tmp_path / "t.wav", tone(1000.0, 0.1, 3.0))
    r = analyse(eng, p, 0.0, 0.6)
    ws = " ".join(r["warnings"])
    assert "shorter than 1 s" in ws and "start-up" in ws


def test_band_near_nyquist_is_skipped_not_invented(eng, tmp_path):
    fs = 16000
    t = np.arange(fs * 6) / fs
    x = (0.1 * np.sin(2 * math.pi * 1000 * t)).astype(np.float32)
    path = tmp_path / "lowfs.wav"
    wavfile.write(str(path), fs, x)
    r = analyse(eng, str(path), 2.0, 5.0)
    L = mvec(r["L"])
    assert math.isnan(L[7])                              # 8 kHz band edge is above Nyquist
    assert not math.isnan(L[4])
    assert any("8000 Hz band skipped" in w for w in r["warnings"])


def test_clipping_is_flagged(eng, tmp_path):
    x = np.clip(tone(1000.0, 0.9), -1, 1)
    r = analyse(eng, write(tmp_path / "clip.wav", x), 2.0, 9.0)
    assert any("clipping" in w for w in r["warnings"])


# --------------------------------------------------------- background subtraction (analytic)
def test_background_subtraction_energy_formula(eng):
    r = eng.nb_background_subtract(matlab.double([60.0] * 8), matlab.double([50.0] * 8))
    assert mvec(r["Lcorr"])[0] == pytest.approx(10 * math.log10(1e6 - 1e5), abs=1e-9)        # 59.542
    assert list(r["status"]) == ["ok"] * 8


def test_background_validity_thresholds(eng):
    ls = matlab.double([52.0, 54.0, 55.0, 56.0, 65.0, 50.0, 50.0, 50.0])
    lb = matlab.double([50.0] * 8)
    r = eng.nb_background_subtract(ls, lb)
    # DeltaL: 2 (<=3 invalid), 4 and 5 (marginal), exactly 6 and 15 (ok), 0 (invalid)
    assert list(r["status"])[:5] == ["invalid", "marginal", "marginal", "ok", "ok"]
    corr = mvec(r["Lcorr"])
    assert math.isnan(corr[0]) and math.isnan(corr[5])                                         # <= 3 dB -> NaN, not a number
    assert corr[1] == pytest.approx(10 * math.log10(10 ** 5.4 - 10 ** 5.0), abs=1e-9)
    assert any("invalid" in w for w in r["warnings"])


def test_background_recording_end_to_end(eng, tmp_path):
    rng = np.random.default_rng(3)
    bg = 0.01 * rng.standard_normal(FS * 8)
    sig = bg + tone(1000.0, 0.1, 8.0)
    ps, pb = write(tmp_path / "s.wav", sig), write(tmp_path / "b.wav", bg)
    r = analyse(eng, ps, 2.0, 7.0, paPerUnit=20.0, background={"file": pb, "start": 2.0, "stop": 7.0})
    assert str(r["subtraction"]["status"][4]) == "ok"
    # 1 kHz: tone dominates; corrected level equals the tone level to well under 0.2 dB
    assert mvec(r["Lused"])[4] == pytest.approx(20 * math.log10(0.1 * 20.0 / 20e-6), abs=0.2)


# --------------------------------------------------------- L_W estimate
def forward_lp(eng, lw, hs, hm, dp, G, atm):
    c = dict(Lw=matlab.double(lw), hs=hs, hr=hm, dp=dp, G=G, atm=atm)
    return mvec(eng.run_acoustic_case(c)["Lp"])


def test_estimate_lw_round_trips_the_forward_model(eng):
    lw = [88.0, 93.0, 98.0, 101.0, 99.0, 95.0, 90.0, 84.0]
    G = {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}
    atm = {"T_C": 15.0, "RH": 60.0, "p_kPa": 101.325}
    lp = forward_lp(eng, lw, 1.5, 1.2, 30.0, G, atm)
    est = eng.nb_estimate_lw(matlab.double(lp), {"hs": 1.5, "hm": 1.2, "dp": 30.0, "dh": 0.0}, G, atm)
    assert mvec(est["Lw"]) == pytest.approx(lw, abs=1e-9)
    assert any("one microphone" in w for w in est["warnings"])


def test_estimate_lw_keeps_nan_bands_and_warns_near_field(eng):
    lp = [60.0, float("nan"), 60.0, 60.0, 60.0, 60.0, 60.0, 60.0]
    est = eng.nb_estimate_lw(matlab.double(lp), {"hs": 1.0, "hm": 1.0, "dp": 3.0, "dh": 0.0},
                             {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}, {"T_C": 15.0, "RH": 60.0, "p_kPa": 101.325},
                             matlab.double([0.0] * 8), 4.0)
    assert math.isnan(mvec(est["Lw"])[1])
    assert any("near-field" in w for w in est["warnings"])


def test_directivity_correction_is_applied(eng):
    G = {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}
    atm = {"T_C": 15.0, "RH": 60.0, "p_kPa": 101.325}
    g = {"hs": 1.5, "hm": 1.2, "dp": 30.0, "dh": 0.0}
    lp = matlab.double([70.0] * 8)
    a = mvec(eng.nb_estimate_lw(lp, g, G, atm)["Lw"])
    b = mvec(eng.nb_estimate_lw(lp, g, G, atm, matlab.double([3.0] * 8))["Lw"])
    assert [x - y for x, y in zip(a, b)] == pytest.approx([3.0] * 8, abs=1e-9)       # L_W = Lp - Dc + A


def test_uncalibrated_recording_blocks_lw_estimation(eng, tmp_path):
    p = write(tmp_path / "t.wav", tone(1000.0, 0.1))
    est = {"g": {"hs": 1.5, "hm": 1.2, "dp": 30.0, "dh": 0.0}, "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
           "atm": {"T_C": 15.0, "RH": 60.0, "p_kPa": 101.325}}
    with pytest.raises(matlab.engine.MatlabExecutionError, match="No calibration"):
        analyse(eng, p, 2.0, 9.0, estimate=est)
    ok = analyse(eng, p, 2.0, 9.0, paPerUnit=20.0, estimate=est)
    assert len(mvec(ok["lw"]["Lw"])) == 8


def test_full_pipeline_recording_to_lw(eng, tmp_path):
    # Source tone of known L_W propagated by the forward model, "recorded" with a known sensitivity.
    lw_true = [60.0, 60.0, 60.0, 60.0, 100.0, 60.0, 60.0, 60.0]
    G = {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5}
    atm = {"T_C": 15.0, "RH": 60.0, "p_kPa": 101.325}
    lp = forward_lp(eng, lw_true, 1.5, 1.2, 30.0, G, atm)
    rms_pa = 20e-6 * 10 ** (lp[4] / 20)                    # 1 kHz tone pressure at the microphone
    pa_per_unit = 10.0
    path = write(tmp_path / "rec.wav", tone(1000.0, rms_pa / pa_per_unit))
    est = {"g": {"hs": 1.5, "hm": 1.2, "dp": 30.0, "dh": 0.0}, "G": G, "atm": atm}
    r = analyse(eng, path, 2.0, 9.0, paPerUnit=pa_per_unit, estimate=est)
    assert mvec(r["lw"]["Lw"])[4] == pytest.approx(100.0, abs=0.2)           # recovered through filter bank + inverse chain


# ---------------------------------------------------------------- no toolbox dependency
def test_butter_sos_matches_scipy(eng):
    # nb_butter_sos replaces butter()+zp2sos() of the Signal Processing Toolbox. scipy is an independent implementation.
    from scipy import signal

    worst = 0.0
    for fs in (22050, 44100, 48000, 96000):
        for order, f1, f2 in [(3, 44.5, 89.1), (3, 707.1, 1414.2), (3, 5657.0, 11314.0), (2, 900.0, 1100.0), (2, 225.0, 275.0)]:
            wn = [f1 / (fs / 2), f2 / (fs / 2)]
            if wn[1] >= 0.98:
                continue
            got = np.array(eng.nb_butter_sos(float(order), matlab.double([wn])))
            ref = signal.butter(order, wn, btype="bandpass", output="sos")
            w = np.pi * np.logspace(np.log10(wn[0] / 20), np.log10(min(0.999, wn[1] * 8)), 1500)
            _, h_got = signal.sosfreqz(got, worN=w)
            _, h_ref = signal.sosfreqz(ref, worN=w)
            worst = max(worst, float(np.max(np.abs(20 * np.log10(np.abs(h_got) / np.abs(h_ref))))))
            assert got.shape == (order, 6)
            assert np.all(np.abs(np.roots(got[0, 3:6])) < 1.0)
    assert worst < 1e-6, f"worst response difference {worst:.3e} dB"


def test_solver_library_needs_no_toolbox(eng):
    # Ask MATLAB which products every .m file of the library depends on: base MATLAB only.
    eng.eval(
        "fl = dir(fullfile('%s','*.m')); nm = fullfile({fl.folder},{fl.name});"
        "[~,pr] = matlab.codetools.requiredFilesAndProducts(nm); prodNames = strjoin({pr.Name}, '|');" % str(CORE).replace("\\", "/"),
        nargout=0,
    )
    assert eng.workspace["prodNames"] == "MATLAB", eng.workspace["prodNames"]
