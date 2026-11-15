"""Managed MATLAB execution worker with hot reload.

One thread owns the single MATLAB Engine session, so jobs can never mutate it
concurrently. Before every job the worker re-hashes the allow-listed .m files.
If any hash changed it clears MATLAB's function cache, refreshes the path, and
rebuilds the dependency fingerprints. The result cache key contains the
inputs AND the fingerprint of every .m file the entry point depends on, so a
result computed with an older file version is never reused.

Only functions whose files live in the configured library folder can be
called. There is no eval endpoint.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import queue
import re
import threading
import time
from concurrent.futures import Future
from typing import Any

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MatlabWorker:
    def __init__(self, library_dir: str | pathlib.Path, startup_args: str = "-nodesktop -nosplash"):
        self.library_dir = pathlib.Path(library_dir).resolve()
        if not self.library_dir.is_dir():
            raise FileNotFoundError(self.library_dir)
        self._startup_args = startup_args
        self._q: "queue.Queue[tuple | None]" = queue.Queue()
        self._eng = None
        self._hashes: dict[str, str] = {}
        self._cache: dict[str, dict] = {}
        self.stats = {"runs": 0, "cache_hits": 0, "reloads": 0}
        self.watching = False
        self._ready = threading.Event()
        self._start_error: BaseException | None = None
        self._thread = threading.Thread(target=self._loop, name="matlab-worker", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ API
    def wait_ready(self, timeout: float = 180.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("MATLAB Engine did not start in time")
        if self._start_error:
            raise RuntimeError(f"MATLAB Engine failed to start: {self._start_error}")

    def run(self, entry: str, inputs: dict[str, Any], use_cache: bool = True, timeout: float = 600.0) -> dict:
        """Run an allow-listed library function that takes one struct and returns one struct."""
        fut: Future = Future()
        self._q.put((entry, inputs, use_cache, fut))
        return fut.result(timeout)

    def run_call(self, entry: str, args: list[Any], timeout: float = 600.0) -> Any:
        """Call an allow-listed library function with positional arguments (strings / numbers). Not cached."""
        fut: Future = Future()
        self._q.put(("call", entry, args, fut))
        return fut.result(timeout)

    def refresh(self) -> dict:
        """Force the hash check and function-cache clear now (the 'Refresh MATLAB functions' button)."""
        fut: Future = Future()
        self._q.put(("refresh", fut))
        return fut.result(120)

    def start_watch(self, interval: float = 2.0) -> None:
        """Automatic watch mode: poll the .m hashes and refresh MATLAB when any file changes."""
        if self.watching:
            return
        self.watching = True

        def poll():
            last = {p.name: _sha256(p) for p in self.library_dir.glob("*.m")}
            while self.watching:
                time.sleep(interval)
                try:
                    now = {p.name: _sha256(p) for p in self.library_dir.glob("*.m")}
                    if now != last:
                        last = now
                        self.refresh()
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=poll, name="matlab-watch", daemon=True).start()

    def stop_watch(self) -> None:
        self.watching = False

    def functions(self) -> list[dict]:
        """Registry rows: name, path, size, mtime, sha256, dependencies."""
        rows = []
        for p in sorted(self.library_dir.glob("*.m")):
            first = next((ln.strip() for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip().startswith("function")), "")
            rows.append({
                "name": p.stem, "path": str(p), "mtime": p.stat().st_mtime, "signature": first,
                "sha256": _sha256(p), "dependencies": sorted(self._deps(p.stem) - {p.stem}),
            })
        return rows

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=30)

    # ------------------------------------------------------- dependency data
    def _stems(self) -> set[str]:
        return {p.stem for p in self.library_dir.glob("*.m")}

    def _deps(self, entry: str) -> set[str]:
        """Transitive set of library functions referenced (identifier scan) from entry."""
        stems = self._stems()
        seen: set[str] = set()
        todo = [entry]
        while todo:
            name = todo.pop()
            if name in seen or name not in stems:
                continue
            seen.add(name)
            text = (self.library_dir / f"{name}.m").read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"%.*", "", text)  # drop comments so words in docs are not dependencies
            for ident in set(_IDENT.findall(text)):
                if ident in stems and ident not in seen:
                    todo.append(ident)
        return seen

    def dependency_fingerprint(self, entry: str) -> dict[str, str]:
        return {n: _sha256(self.library_dir / f"{n}.m") for n in sorted(self._deps(entry))}

    # ----------------------------------------------------------- worker side
    def _loop(self) -> None:
        try:
            import matlab.engine  # imported here so the module loads without MATLAB

            self._eng = matlab.engine.start_matlab(self._startup_args)
            self._eng.addpath(str(self.library_dir), nargout=0)
            self._hashes = {p.name: _sha256(p) for p in self.library_dir.glob("*.m")}
        except BaseException as exc:  # noqa: BLE001
            self._start_error = exc
            self._ready.set()
            return
        self._ready.set()
        while True:
            item = self._q.get()
            if item is None:
                break
            if item[0] == "refresh":
                try:
                    item[1].set_result({"reloaded": self._refresh_if_changed(), "stats": dict(self.stats)})
                except BaseException as exc:  # noqa: BLE001
                    item[1].set_exception(exc)
                continue
            if item[0] == "call":
                _, entry, args, fut = item
                try:
                    fut.set_result(self._execute_call(entry, args))
                except BaseException as exc:  # noqa: BLE001
                    fut.set_exception(exc)
                continue
            entry, inputs, use_cache, fut = item
            try:
                fut.set_result(self._execute(entry, inputs, use_cache))
            except BaseException as exc:  # noqa: BLE001
                fut.set_exception(exc)
        try:
            self._eng.quit()
        except Exception:  # noqa: BLE001
            pass

    def _refresh_if_changed(self) -> bool:
        now = {p.name: _sha256(p) for p in self.library_dir.glob("*.m")}
        if now == self._hashes:
            return False
        # Files added, removed or edited: make MATLAB forget compiled copies and re-read the path.
        self._eng.eval("clear functions; clear classes;", nargout=0)
        self._eng.rmpath(str(self.library_dir), nargout=0)
        self._eng.addpath(str(self.library_dir), nargout=0)
        self._eng.eval("rehash;", nargout=0)
        self._hashes = now
        self._cache.clear()  # belt and braces; keys also embed the fingerprint
        self.stats["reloads"] += 1
        return True

    def _execute_call(self, entry: str, args: list) -> Any:
        if entry not in self._stems():
            raise PermissionError(f"'{entry}' is not a function in the allow-listed library")
        self._refresh_if_changed()
        fn = getattr(self._eng, entry)
        self.stats["runs"] += 1
        return _from_matlab(fn(*[_to_matlab(a) for a in args]))

    def _execute(self, entry: str, inputs: dict, use_cache: bool) -> dict:
        if entry not in self._stems():
            raise PermissionError(f"'{entry}' is not a function in the allow-listed library")
        reloaded = self._refresh_if_changed()
        fp = self.dependency_fingerprint(entry)
        key = hashlib.sha256(
            json.dumps({"entry": entry, "inputs": inputs, "deps": fp}, sort_keys=True, default=_json_default).encode()
        ).hexdigest()
        if use_cache and key in self._cache:
            self.stats["cache_hits"] += 1
            res = dict(self._cache[key])
            res["_meta"] = {**res["_meta"], "cache_hit": True, "reloaded": reloaded}
            return res
        t0 = time.time()
        fn = getattr(self._eng, entry)
        raw = fn(_to_matlab(inputs))
        result = _from_matlab(raw)
        result["_meta"] = {
            "entry": entry, "cache_key": key, "dependency_sha256": fp,
            "seconds": round(time.time() - t0, 4), "cache_hit": False, "reloaded": reloaded,
        }
        self.stats["runs"] += 1
        self._cache[key] = result
        return dict(result)


def _json_default(o):  # numpy scalars etc.
    try:
        return o.item()
    except Exception:  # noqa: BLE001
        return str(o)


def _to_matlab(x):
    import matlab

    if isinstance(x, dict):
        return {k: _to_matlab(v) for k, v in x.items()}
    if x is None:
        return matlab.double([])
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, (list, tuple)):
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x):
            return matlab.double([float(v) for v in x])
        if (
            x
            and all(isinstance(r, (list, tuple)) and r for r in x)
            and len({len(r) for r in x}) == 1
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for r in x for v in r)
        ):
            return matlab.double([[float(v) for v in r] for r in x])      # rectangular -> matrix
        return [_to_matlab(v) for v in x]
    return x


def _from_matlab(x):
    import matlab

    if isinstance(x, dict):
        return {k: _from_matlab(v) for k, v in x.items()}
    logical_t = getattr(matlab, "logical", None)
    kinds = [(matlab.double, float)]
    if logical_t is not None:
        kinds.append((logical_t, bool))
    for mtype, conv in kinds:
        if isinstance(x, mtype):
            rows, cols = x.size
            if rows == 0 or cols == 0:
                return []
            if rows == 1 and cols == 1:
                return conv(x[0][0])
            if rows == 1:                      # row vector -> flat list
                return [conv(v) for v in x[0]]
            if cols == 1:                      # column vector -> flat list
                return [conv(row[0]) for row in x]
            return [[conv(v) for v in row] for row in x]   # matrix -> list of rows
    if isinstance(x, (list, tuple)):
        return [_from_matlab(v) for v in x]
    return x
