import { useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { LabResult, LabRow, LabScene, ProjectRow, labCatalog, labLast, labLoad, labRun, labScene } from "./api";

const COLOR: Record<string, string> = { PASS: "okc", FAIL: "badc", BLOCKED: "warnc", SKIP: "muted", EXTERNAL: "muted" };
const f = (v: number | null | undefined, n = 3) => (v == null || !Number.isFinite(v) ? "-" : v.toFixed(n));

export default function TestLabView({ active }: { active: ProjectRow | null }) {
  const [cat, setCat] = useState<LabRow[]>([]);
  const [res, setRes] = useState<Record<string, LabResult>>({});
  const [sel, setSel] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [scene, setScene] = useState<LabScene | null>(null);
  const [meta, setMeta] = useState<string>("");
  const plot = useRef<HTMLDivElement>(null);

  const ingest = (s: { results: LabResult[]; seconds: number | null; meta: { matlab_release: string } | null }) => {
    setRes((old) => ({ ...old, ...Object.fromEntries(s.results.map((r) => [r.id, r])) }));
    setMeta(`${s.results.length} tests in ${s.seconds ?? "?"} s, MATLAB ${s.meta?.matlab_release ?? ""}`);
  };

  useEffect(() => {
    labCatalog().then(setCat).catch((e) => setErr(String(e)));
    labLast().then(ingest).catch(() => undefined);
  }, []);

  async function run(label: string, body: { ids?: string[]; group?: string }) {
    setBusy(label);
    setErr(null);
    try {
      ingest(await labRun(body));
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  const row = sel ? res[sel] : undefined;
  const meta0 = sel ? cat.find((c) => c.id === sel) : undefined;

  useEffect(() => {
    setScene(null);
    if (sel && sel.startsWith("G3-T")) labScene(sel).then(setScene).catch(() => setScene(null));
  }, [sel]);

  useEffect(() => {
    const el = plot.current;
    if (!el || !scene) return;
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim() || "#222";
    const line = css.getPropertyValue("--line").trim() || "#ddd";
    const tr: Plotly.Data[] = [];
    scene.areas.forEach((a, i) =>
      tr.push({ type: "scatter", mode: "lines", x: [...a.x, a.x[0]], y: [...a.y, a.y[0]], fill: "toself", fillcolor: `rgba(46,139,87,${0.08 + 0.35 * a.G})`, line: { color: "rgba(46,139,87,0.6)", width: 1 }, name: `ground G=${a.G}`, hoverinfo: "name" } as Plotly.Data),
    );
    scene.obstacles.forEach((o, i) =>
      tr.push({ type: "scatter", mode: "lines", x: o.x.length > 2 ? [...o.x, o.x[0]] : o.x, y: o.y.length > 2 ? [...o.y, o.y[0]] : o.y, fill: o.x.length > 2 ? "toself" : "none", fillcolor: "rgba(192,57,43,0.3)", line: { color: "#c0392b", width: o.x.length > 2 ? 2 : 4 }, name: `object ${i + 1}, top ${o.top} m`, hoverinfo: "name" } as Plotly.Data),
    );
    tr.push({ type: "scatter", mode: "lines", x: [scene.S[0], scene.R[0]], y: [scene.S[1], scene.R[1]], line: { color: "#7f8c8d", dash: "dot" }, name: "direct line (plan)" } as Plotly.Data);
    tr.push({ type: "scatter", mode: "markers+text", x: [scene.S[0], scene.R[0]], y: [scene.S[1], scene.R[1]], text: ["S", "R"], textposition: "top center", marker: { size: 9, color: ink }, name: "S / R" } as unknown as Plotly.Data);
    Plotly.react(el, tr, {
      margin: { l: 44, r: 8, t: 6, b: 36 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", showlegend: false,
      font: { size: 11, color: ink }, xaxis: { title: { text: "x, m" }, gridcolor: line }, yaxis: { title: { text: "y, m" }, gridcolor: line, scaleanchor: "x" },
    }, { displayModeBar: false, responsive: true });
  }, [scene]);

  const groups = Array.from(new Set(cat.map((c) => c.group)));
  const count = (st: string) => Object.values(res).filter((r) => r.status === st).length;

  return (
    <div>
      <h2>Test Lab</h2>
      <p className="note">
        Every test executes the production MATLAB functions listed for it. Expected values come from the standards, the ISO/TR tables, or hand derivation, never from the code under test.
        Passing is not an ISO certification. ISO/TR 17534-3 reference values target ISO 9613-2:1996, so G3 runs in a labelled 1996 compatibility mode.
      </p>
      <div className="tabs">
        <button className="primary" disabled={!!busy} onClick={() => void run("all", {})}>{busy === "all" ? "Running all" : "Run all tests"}</button>
        {groups.map((g) => (
          <button key={g} disabled={!!busy || g.startsWith("G6")} onClick={() => void run(g, { group: g.slice(0, 2) })}>{busy === g ? "Running" : `Run ${g.slice(0, 2)}`}</button>
        ))}
        <a href="/api/testlab/report.md" download><button>Report (Markdown)</button></a>
        <a href="/api/testlab/report.json" download><button>Machine-readable log (JSON)</button></a>
      </div>
      <p className="note">
        {meta} PASS {count("PASS")}, FAIL <span className={count("FAIL") ? "badc" : ""}>{count("FAIL")}</span>, BLOCKED {count("BLOCKED")}, SKIP {count("SKIP")}, EXTERNAL {count("EXTERNAL")} (BLOCKED, SKIP and EXTERNAL are not passes).
      </p>
      {err && <div className="error">{err}</div>}

      <div className="labgrid">
        <div>
          {groups.map((g) => (
            <div key={g}>
              <h2>{g}</h2>
              <table>
                <tbody>
                  {cat.filter((c) => c.group === g).map((c) => {
                    const r = res[c.id];
                    const st = r?.status ?? (c.status0 || "not run");
                    return (
                      <tr key={c.id} className={sel === c.id ? "selrow" : ""} onClick={() => setSel(c.id)} style={{ cursor: "pointer" }}>
                        <td className="mono">{c.id.replace(/^G\d-/, "")}</td>
                        <td style={{ textAlign: "left" }}>{c.title}</td>
                        <td className={COLOR[st] ?? "muted"}>{st}</td>
                        <td>{r && r.n > 0 ? `${r.n_pass}/${r.n}` : ""}</td>
                        <td><button onClick={(e) => { e.stopPropagation(); void run(c.id, { ids: [c.id] }); }} disabled={!!busy || c.group.startsWith("G6")}>Run</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ))}
        </div>

        <div style={{ position: "sticky", top: 0, alignSelf: "start", maxHeight: "calc(100vh - 70px)", overflow: "auto" }}>
          {meta0 && (
            <div className="inspector" style={{ marginTop: 0 }}>
              <h2>{meta0.id} {meta0.title}</h2>
              <p className="note">Source: {meta0.source}</p>
              <p className="note">Production functions called: {meta0.calls.length ? meta0.calls.join(", ") : "none (not executed here)"}</p>
              {row && <p className={COLOR[row.status]}><strong>{row.status}</strong> {row.detail && <span className="note">{row.detail}</span>}</p>}
              {row && row.max_abs_error != null && <p className="note">Max |error| {f(row.max_abs_error, 4)}; method: {meta0.group}</p>}
              {scene && (
                <>
                  <div ref={plot} style={{ width: "100%", height: 260 }} />
                  <div className="tabs">
                    <button disabled={!active} onClick={() => active && void labLoad(meta0.id, active.id).then((c) => setErr(`Loaded as case "${c.name}" in project "${active.name}". Open the Projects page to run and edit it.`)).catch((e) => setErr(String(e)))}>
                      Load as editable case in the active project
                    </button>
                    {!active && <span className="note">Select a project on the Projects page first.</span>}
                  </div>
                </>
              )}
              {row && row.n > 0 && (
                <table>
                  <thead><tr><th>Quantity</th><th>Expected</th><th>Actual</th><th>Error</th><th>Tolerance</th><th>Result</th></tr></thead>
                  <tbody>
                    {row.labels.map((l, i) => (
                      <tr key={i} className={row.pass[i] || row.status === "BLOCKED" ? "" : "exc"}>
                        <td>{l}</td><td>{f(row.expected[i])}</td><td>{f(row.actual[i])}</td><td>{f(row.err[i], 4)}</td><td>{f(row.tol[i], 4)}</td>
                        <td>{row.status === "BLOCKED" ? "blocked" : row.pass[i] ? "pass" : "FAIL"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
          {!meta0 && <p className="muted">Select a test to see its source, inputs, expected and actual values.</p>}
        </div>
      </div>
    </div>
  );
}
