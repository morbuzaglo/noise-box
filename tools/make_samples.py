"""Generate the SYNTHETIC demo data in samples/. Nothing here is measured or surveyed.

    python tools/make_samples.py [output_dir]

Files
  audio/calibrator_94dB_1kHz.wav   1 kHz tone recorded at rms 0.05 (a 94 dB calibrator, sensitivity 20.05 Pa/unit)
  audio/machine_example.wav        synthetic machine noise (band-limited noise + hum), 12 s, rms-scaled so that with
                                   the calibrator above it reads about 80 dB re 20 uPa
  audio/background_example.wav     synthetic background noise, 8 s, about 55 dB with the same calibration
  terrain/ridge_dem.asc            ESRI ASCII grid, 61 x 61 cells of 5 m, a 10 m ridge across the middle (metres)
  terrain/hill_dem.asc             Gaussian hill, 14 m
  terrain/profile_ridge.csv        2D X-Z profile (x, z) of the same ridge
  scene/wall_with_fabric.json      finite wall carrying a light fabric (surface mass 0.4 kg/m2)
  scene/receivers.json             named receivers
  scene/source_presets.json        SYNTHETIC example spectrum (not a measured or calibrated source)
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np
from scipy.io import wavfile

FS = 44100


def tone(f, rms, seconds):
    t = np.arange(int(FS * seconds)) / FS
    return rms * math.sqrt(2) * np.sin(2 * math.pi * f * t)


def band_noise(rng, seconds, rms, lo, hi):
    n = int(FS * seconds)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / FS)
    spec[(f < lo) | (f > hi)] = 0
    x = np.fft.irfft(spec, n)
    return x * (rms / np.sqrt(np.mean(x ** 2)))


def write_wav(path: pathlib.Path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), FS, x.astype(np.float32))


def ascii_grid(path: pathlib.Path, Z: np.ndarray, cs: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    ny, nx = Z.shape
    lines = [f"ncols {nx}", f"nrows {ny}", "xllcorner 0", "yllcorner 0", f"cellsize {cs}", "NODATA_value -9999"]
    for row in Z[::-1]:
        lines.append(" ".join(f"{v:.3f}" for v in row))
    path.write_text("\n".join(lines), encoding="utf-8")


def make(out: pathlib.Path) -> dict:
    rng = np.random.default_rng(42)
    write_wav(out / "audio" / "calibrator_94dB_1kHz.wav", tone(1000.0, 0.05, 8.0))
    machine = band_noise(rng, 12.0, 0.04, 100, 3000) + tone(125.0, 0.03, 12.0) + tone(500.0, 0.02, 12.0)
    write_wav(out / "audio" / "machine_example.wav", machine)
    write_wav(out / "audio" / "background_example.wav", band_noise(rng, 8.0, 0.0012, 50, 8000))

    cs, n = 5.0, 61
    xs = np.arange(n) * cs
    X, Y = np.meshgrid(xs, xs)
    ridge = np.maximum(0.0, 10.0 - np.abs(X - xs[-1] / 2) / 6.0)
    hill = 14.0 * np.exp(-((X - xs[-1] / 2) ** 2 + (Y - xs[-1] / 2) ** 2) / (2 * (0.16 * xs[-1]) ** 2))
    ascii_grid(out / "terrain" / "ridge_dem.asc", ridge, cs)
    ascii_grid(out / "terrain" / "hill_dem.asc", hill, cs)
    (out / "terrain" / "profile_ridge.csv").write_text("x,z\n" + "\n".join(f"{x:g},{max(0.0, 10.0 - abs(x - 150) / 6.0):.3f}" for x in range(0, 301, 10)), encoding="utf-8")

    scene = out / "scene"
    scene.mkdir(parents=True, exist_ok=True)
    (scene / "wall_with_fabric.json").write_text(json.dumps({
        "note": "SYNTHETIC example: a 40 m wall, 5 m high, light fabric (0.4 kg/m2) - below the 10 kg/m2 ISO screening minimum, so it is an engineering estimate only",
        "obstacle": {"kind": "wall", "x": [150, 150], "y": [130, 170], "h": 5, "material": {"surface_mass": 0.4, "openness": 0.05}}}, indent=2), encoding="utf-8")
    (scene / "receivers.json").write_text(json.dumps([
        {"name": "R1 behind wall", "x": 200, "y": 150, "h": 1.5}, {"name": "R2 beside wall", "x": 200, "y": 215, "h": 1.5}], indent=2), encoding="utf-8")
    (scene / "source_presets.json").write_text(json.dumps({
        "SYNTHETIC example (not measured, not calibrated)": {"Lw_dB_re_1pW_unweighted": [90, 95, 100, 100, 98, 95, 90, 85]}}, indent=2), encoding="utf-8")
    (out / "README.md").write_text(__doc__ or "", encoding="utf-8")
    return {"dir": str(out)}


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1] / "samples"
    print(make(target))
