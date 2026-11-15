import { useCallback, useEffect, useState } from "react";
import {
  BANDS, CaseRow, Comparison, ProjectRow, compareCases, createProject, deleteCase, deleteProject, duplicateCase, duplicateProject,
  exportUrl, getCase, getProject, listProjects, patchProject, runStoredCase,
} from "./api";

const f1 = (v: number | null | undefined) => (v == null ? "no data" : v.toFixed(1));
const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString() : "not run");

interface Props {
  active: ProjectRow | null;
  setActive: (p: ProjectRow | null) => void;
  onOpen: (c: CaseRow) => void; // open the stored case in its editor view
}

export default function ProjectsView({ active, setActive, onOpen }: Props) {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [detail, setDetail] = useState<CaseRow | null>(null);
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [grid, setGrid] = useState(false);
  const [dup, setDup] = useState<{ id: string; name: string; T: string; RH: string; mode: string; Lw: string[]; raw: string } | null>(null);

  const reload = useCallback(async () => {
    try {
      setProjects(await listProjects());
      if (active) {
        const p = await getProject(active.id);
        setCases(p.cases);
        setActive(p);
      } else setCases([]);
    } catch (e) {
      setErr(String(e));
    }
  }, [active?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void reload();
  }, [reload]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setErr(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  };

  async function showCompare() {
    if (!active) return;
    setCmp(await compareCases(active.id, picked.length ? picked : cases.map((c) => c.id)));
  }

  function openDup(c: CaseRow) {
    void getCase(c.id).then((full) => {
      const req = (full.input?.request ?? {}) as Record<string, unknown>;
      const atm = (req.atm ?? {}) as Record<string, number>;
      setDup({ id: c.id, name: `${c.name} (variant)`, T: String(atm.T_C ?? ""), RH: String(atm.RH ?? ""), mode: String(req.mode ?? "iso2024"), Lw: ((req.Lw as number[]) ?? []).map(String), raw: "{}" });
    });
  }

  async function submitDup() {
    if (!dup) return;
    let raw: Record<string, unknown> = {};
    try {
      raw = JSON.parse(dup.raw || "{}");
    } catch {
      setErr("The advanced overrides are not valid JSON.");
      return;
    }
    const req: Record<string, unknown> = { ...(raw.request as Record<string, unknown> | undefined) };
    const atm: Record<string, number> = { ...((req.atm as Record<string, number> | undefined) ?? {}) };
    if (dup.T.trim() !== "") atm.T_C = parseFloat(dup.T);
    if (dup.RH.trim() !== "") atm.RH = parseFloat(dup.RH);
    if (Object.keys(atm).length) req.atm = atm;
    req.mode = dup.mode;
    if (dup.Lw.length === 8 && dup.Lw.every((v) => v.trim() !== "")) req.Lw = dup.Lw.map(parseFloat);
    await act("duplicate", () => duplicateCase(dup.id, dup.name, { ...raw, request: req }));
    setDup(null);
  }

  return (
    <div>
      <h2>Projects</h2>
      <div className="tabs">
        <select value={active?.id ?? ""} onChange={(e) => setActive(projects.find((p) => p.id === e.target.value) ?? null)} aria-label="Active project">
          <option value="">(no project selected)</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.n_cases ?? 0} cases)</option>)}
        </select>
        <input placeholder="New project name" value={newName} onChange={(e) => setNewName(e.target.value)} />
        <button disabled={!newName.trim()} onClick={() => void act("create", async () => { const p = await createProject(newName.trim()); setActive(p); setNewName(""); })}>Create project</button>
        {active && <button onClick={() => { const n = prompt("Rename project", active.name); if (n) void act("rename", () => patchProject(active.id, { name: n })); }}>Rename</button>}
        {active && <button onClick={() => void act("dup", async () => { const p = await duplicateProject(active.id); setActive(p); })}>Duplicate project</button>}
        {active && <button onClick={() => { if (confirm(`Delete project "${active.name}" and all its cases and stored assets? This cannot be undone.`)) void act("delete", async () => { await deleteProject(active.id); setActive(null); }); }}>Delete project</button>}
      </div>
      {err && <div className="error">{err}</div>}
      {!active && <p className="muted">Select or create a project. A project holds cases that share terrain, receivers and limits; each case stores its input snapshot, result, warnings and the MATLAB code version that produced it.</p>}

      {active && (
        <>
          <h2>Cases in "{active.name}"</h2>
          <p className="note">Create cases with "Save as case" in the Flat ground, 2D section and 3D terrain views. Select cases to compare or export; none selected = all.</p>
          <table>
            <thead><tr><th></th><th>Case</th><th>Type</th><th>Status</th><th>Executed</th><th>Code</th><th></th></tr></thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id}>
                  <td><input type="checkbox" checked={picked.includes(c.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, c.id] : picked.filter((x) => x !== c.id))} /></td>
                  <td>{c.name}</td>
                  <td>{c.kind}</td>
                  <td className={c.status.startsWith("failed") ? "badc" : ""}>{c.status}</td>
                  <td>{when(c.executed)}</td>
                  <td className="mono">{c.fingerprint?.md5?.[0]?.slice(0, 8) ?? "-"}</td>
                  <td>
                    <button disabled={!!busy} onClick={() => void act("run", async () => { setDetail(await runStoredCase(c.id)); })}>{busy === "run" ? "Running" : c.status === "completed" ? "Rerun" : "Run"}</button>{" "}
                    <button className="primary" onClick={() => void getCase(c.id).then(onOpen)}>Open in view</button>{" "}
                    <button onClick={() => void getCase(c.id).then(setDetail)}>Results</button>{" "}
                    <button onClick={() => openDup(c)}>Duplicate</button>{" "}
                    <button onClick={() => { if (confirm(`Delete case "${c.name}"?`)) void act("del", () => deleteCase(c.id)); }}>x</button>
                  </td>
                </tr>
              ))}
              {cases.length === 0 && <tr><td colSpan={7} className="muted">No cases yet.</td></tr>}
            </tbody>
          </table>
          <div className="tabs">
            <button disabled={cases.length < 1} onClick={() => void showCompare()}>Compare</button>
            <a href={exportUrl(active.id, picked, grid)} download><button disabled={cases.length < 1}>Export to Excel (one sheet per case)</button></a>
            <label className="note"><input type="checkbox" checked={grid} onChange={(e) => setGrid(e.target.checked)} /> include map grids as extra sheets</label>
          </div>
        </>
      )}

      {dup && (
        <div className="inspector">
          <h2>Duplicate case and change selected variables</h2>
          <label className="field"><span>New case name</span><input value={dup.name} onChange={(e) => setDup({ ...dup, name: e.target.value })} /></label>
          <label className="field"><span>Temperature, deg C</span><input value={dup.T} onChange={(e) => setDup({ ...dup, T: e.target.value })} /></label>
          <label className="field"><span>Relative humidity, %</span><input value={dup.RH} onChange={(e) => setDup({ ...dup, RH: e.target.value })} /></label>
          <label className="field"><span>Standard</span>
            <select value={dup.mode} onChange={(e) => setDup({ ...dup, mode: e.target.value })}>
              <option value="iso2024">ISO 9613-2:2024 (published)</option>
              <option value="draft2026">DAmd 1 DRAFT (experimental)</option>
            </select></label>
          <div className="bands">{BANDS.map((f, i) => (
            <label key={f} className="band"><span>L_W {f}</span><input value={dup.Lw[i] ?? ""} onChange={(e) => setDup({ ...dup, Lw: dup.Lw.map((v, j) => (j === i ? e.target.value : v)) })} /></label>
          ))}</div>
          <label className="field"><span>Advanced overrides (JSON, merged into the input)</span><textarea rows={3} style={{ width: "100%" }} value={dup.raw} onChange={(e) => setDup({ ...dup, raw: e.target.value })} /></label>
          <div className="tabs"><button className="primary" onClick={() => void submitDup()}>Create variant</button><button onClick={() => setDup(null)}>Cancel</button></div>
        </div>
      )}

      {cmp && (
        <div className="inspector">
          <h2>Comparison: broadband L_p,A, dB(A) (63-8000 Hz bands)</h2>
          <table>
            <thead><tr><th>Receiver</th>{cmp.cases.map((c) => <th key={c.id}>{c.name}{c.mode === "draft2026" ? " [DRAFT]" : ""}</th>)}</tr></thead>
            <tbody>
              {cmp.table.map((r) => (
                <tr key={r.receiver}>
                  <td>{r.receiver}</td>
                  {cmp.cases.map((c) => {
                    const v = r.cases[c.id];
                    return <td key={c.id} className={v?.status === "FAIL" ? "badc" : v?.status === "PASS" ? "okc" : ""}>{v ? `${f1(v.LpA)} ${v.status ?? ""}` : "-"}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <div className="inspector">
          <h2>Case "{detail.name}" ({detail.kind}), {detail.status}</h2>
          {detail.fingerprint && <p className="note mono">Code version: {detail.fingerprint.file.length} MATLAB files; first {detail.fingerprint.file[0]} md5 {detail.fingerprint.md5[0]}</p>}
          {detail.result?.field && <p className="note">Map: {detail.result.field.n_points} points, {detail.result.field.stats.valid} valid, L_p,A range {f1(detail.result.field.stats.LpA_min)} to {f1(detail.result.field.stats.LpA_max)} dB(A).</p>}
          {detail.result && (
            <table>
              <thead><tr><th>Receiver</th><th>Path</th><th>L_p,A</th><th>L_p</th><th>Status</th>{BANDS.map((f) => <th key={f}>{f}</th>)}</tr></thead>
              <tbody>
                {detail.result.receivers.map((q) => (
                  <tr key={q.name} className={q.compliance?.status === "FAIL" ? "exc" : ""}>
                    <td>{q.name}</td><td>{q.valid ? q.path : q.reason}</td><td>{f1(q.out?.LpA_broadband)}</td><td>{f1(q.out?.Lp_broadband)}</td><td>{q.compliance?.status ?? "-"}</td>
                    {BANDS.map((_, i) => <td key={i}>{f1(q.out?.Lp?.[i])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {detail.warnings.length > 0 && <ul className="note">{detail.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
          <p className="note">Validation status: self-authored tests only; no ISO conformance is claimed.</p>
        </div>
      )}
    </div>
  );
}
