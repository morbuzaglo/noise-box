"""Shared fixtures. One MATLAB Engine per test session (startup is ~14 s)."""
import os
import pathlib
import tempfile

import matlab.engine
import pytest

# One data directory for the whole test session (project/case storage resolves it on every call).
os.environ.setdefault("NOISEBOX_DATA", tempfile.mkdtemp(prefix="noisebox-test-"))

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / "matlab" / "core"


@pytest.fixture(scope="session")
def eng():
    e = matlab.engine.start_matlab("-nodesktop -nosplash")
    e.addpath(str(CORE), nargout=0)
    yield e
    e.quit()


def mvec(x):
    """MATLAB vector (row or column) or scalar -> flat list of float."""
    if hasattr(x, "_size"):
        return [float(v) for row in x for v in row]
    try:
        return [float(v) for v in x]
    except TypeError:
        return [float(x)]
