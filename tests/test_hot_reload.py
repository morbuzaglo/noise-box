"""GROUP 6 integration test: MATLAB hot reload through the managed worker.

Edits a COPY of the MATLAB library (never the real one), in the same running
MATLAB session, and checks that the next prediction uses the edited file.
"""
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.matlab_worker import MatlabWorker  # noqa: E402

CASE = {
    "Lw": [100.0] * 8,
    "hs": 2.0, "hr": 1.5, "dp": 100.0,
    "G": {"Gs": 0.5, "Gm": 0.5, "Gr": 0.5},
    "atm": {"T_C": 10.0, "RH": 70.0, "p_kPa": 101.325},
}


@pytest.fixture()
def worker(tmp_path):
    lib = tmp_path / "core"
    shutil.copytree(ROOT / "matlab" / "core", lib)
    w = MatlabWorker(lib)
    w.wait_ready()
    yield w, lib
    w.close()


def test_edit_changes_next_result_without_restart(worker):
    w, lib = worker
    before = w.run("run_acoustic_case", CASE)
    again = w.run("run_acoustic_case", CASE)
    assert again["_meta"]["cache_hit"] is True          # identical input + identical code -> cache
    assert again["Lp"] == before["Lp"]

    # Edit a dependency of the entry point: add 1 dB to A_div.
    f = lib / "nb_adiv.m"
    src = f.read_text(encoding="utf-8")
    assert "A = 20*log10(d/1) + 11;" in src
    f.write_text(src.replace("A = 20*log10(d/1) + 11;", "A = 20*log10(d/1) + 11 + 1;"), encoding="utf-8")

    after = w.run("run_acoustic_case", CASE)
    meta = after["_meta"]
    assert meta["cache_hit"] is False                   # old cached result must NOT be reused
    assert meta["reloaded"] is True
    assert meta["cache_key"] != before["_meta"]["cache_key"]
    assert meta["dependency_sha256"]["nb_adiv"] != before["_meta"]["dependency_sha256"]["nb_adiv"]
    for b, a in zip(before["Lp"], after["Lp"]):
        assert a == pytest.approx(b - 1.0, abs=1e-9)    # exactly the edit
    assert w.stats["reloads"] == 1


def test_revert_restores_original_result(worker):
    w, lib = worker
    f = lib / "nb_adiv.m"
    orig = f.read_text(encoding="utf-8")
    base = w.run("run_acoustic_case", CASE)
    f.write_text(orig.replace("+ 11;", "+ 12;"), encoding="utf-8")
    changed = w.run("run_acoustic_case", CASE)
    assert changed["Lp"][0] == pytest.approx(base["Lp"][0] - 1.0, abs=1e-9)
    f.write_text(orig, encoding="utf-8")
    restored = w.run("run_acoustic_case", CASE)
    assert restored["Lp"] == pytest.approx(base["Lp"], abs=1e-12)


def test_dependency_scan_finds_core_modules(worker):
    w, _ = worker
    deps = set(w.dependency_fingerprint("run_acoustic_case"))
    assert {"nb_adiv", "nb_aatm", "nb_agr", "nb_dz", "nb_abar", "nb_cmet", "nb_bands", "nb_energy_sum"} <= deps


def test_non_library_function_is_rejected(worker):
    w, _ = worker
    with pytest.raises(PermissionError):
        w.run("system", {})
    with pytest.raises(PermissionError):
        w.run("../../evil", {})


def test_result_records_code_fingerprint(worker):
    w, _ = worker
    r = w.run("run_acoustic_case", CASE)
    assert len(r["fingerprint"]["md5"]) >= 8
