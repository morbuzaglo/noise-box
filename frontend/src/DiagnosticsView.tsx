import { useCallback, useEffect, useState } from "react";
import { Diagnostics, FunctionRow, getDiagnostics, getFunctions, refreshMatlab, setWatch } from "./api";

export default function DiagnosticsView() {
  const [d, setD] = useState<Diagnostics | null>(null);
  const [fns, setFns] = useState<FunctionRow[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    try {
      setD(await getDiagnostics());
      setFns(await getFunctions());
    } catch (e) {
      setMsg(String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = fns.filter((r) => r.name.includes(filter));
  return (
    <div>
      <h2>MATLAB connection and function library</h2>
      {d && (
        <dl>
          <dt>Backend state</dt><dd>{d.state}</dd>
          <dt>MATLAB</dt><dd>{d.matlab ? `${d.matlab.release} (${d.matlab.version}), Java ${d.matlab.javaVersion}` : "not connected"}</dd>
          <dt>Python</dt><dd>{d.python} on {d.platform}</dd>
          <dt>Engine requirement</dt><dd>{d.engine_requirement}</dd>
          <dt>Library folder (set NOISEBOX_MATLAB_LIB to change)</dt><dd className="mono">{d.library}</dd>
        </dl>
      )}
      {d?.matlab && (
        <table>
          <caption className="note" style={{ textAlign: "left" }}>For information only: the solver uses base MATLAB and needs none of these toolboxes.</caption>
          <thead><tr><th>Toolbox</th><th>Licensed</th></tr></thead>
          <tbody>{d.matlab.toolboxes.map((t, i) => <tr key={t}><td>{t}</td><td className={d.matlab!.licensed[i] ? "okc" : "muted"}>{d.matlab!.licensed[i] ? "yes" : "no"}</td></tr>)}</tbody>
        </table>
      )}
      <div className="tabs">
        <button className="primary" onClick={() => void refreshMatlab().then((r) => { setMsg(r.reloaded ? "Files had changed: MATLAB function cache cleared and path refreshed." : "No file changes detected."); return load(); }).catch((e) => setMsg(String(e)))}>Refresh MATLAB functions</button>
        <label className="note"><input type="checkbox" checked={d?.watching ?? false} onChange={(e) => void setWatch(e.target.checked).then(load)} /> Watch mode (refresh automatically when a .m file changes)</label>
        <input placeholder="filter by name" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <p className="note">Edit the .m files in your editor; every simulation re-hashes them first, so a changed file always takes effect on the next run and invalidates cached results. The table is read-only: results record the code version that produced them.</p>
      {msg && <div className="note">{msg}</div>}
      <table>
        <thead><tr><th>Function</th><th>Signature</th><th>Modified</th><th>SHA-256</th><th>Verification</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td className="mono" title={r.path}>{r.name}</td>
              <td className="mono" style={{ textAlign: "left" }}>{r.signature}</td>
              <td>{new Date(r.mtime * 1000).toLocaleString()}</td>
              <td className="mono">{r.sha256.slice(0, 12)}</td>
              <td className={r.linked_tests.length ? "okc" : "muted"} title={r.linked_tests.join(", ")}>{r.linked_tests.length ? `${r.linked_tests.length} linked tests` : "no Test Lab test"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
