import { useEffect, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { BANDS, CaseRow, EnclosureIn, Field2DResult, Limits, Mode, runField2D } from "./api";
import { limFromRequest } from "./caseConvert";
import SpectrumChart from "./SpectrumChart";
import SaveCase from "./SaveCase";
import { ProjectRow } from "./api";

interface Props {
  lw: number[];
  G: { Gs: number; Gm: number; Gr: number };
  atm: { T_C: number; RH: number; p_kPa: number };
  mode: Mode;
  ready: boolean;
  enclosure?: EnclosureIn;
  project?: ProjectRow | null;
  initial?: CaseRow; // a stored case opened as if just defined here
}

type Metric = string; // "bb" | "bbA" | "Lp:k" | "LpA:k" | "Abar:k" | "compliance"

const fmt = (v: number | null | undefined, n = 1) => (v == null || !Number.isFinite(v) ? "no data" : v.toFixed(n));
const num = (s: string) => (s.trim() === "" ? null : parseFloat(s));

function groundAt(tx: number[], tz: number[], x: number): number | null {
  for (let i = 0; i < tx.length - 1; i++) {
    if (x >= tx[i] && x <= tx[i + 1]) return tz[i] + ((tz[i + 1] - tz[i]) * (x - tx[i])) / (tx[i + 1] - tx[i]);
  }
  return null;
}

export default function SectionView({ lw, G, atm, mode, ready, enclosure, project, initial }: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const req = (initial?.input?.request ?? {}) as Record<string, any>;
  const lim0 = initial ? limFromRequest(req.limits) : { bands: ["", "", "", "45", "45", "45", "45", "45"], weighting: "Z" as const, overallA: "" };
  const pendingRun = useRef(!!initial);
  const [rcv, setRcv] = useState<{ name: string; x: number; h: number }[]>(() =>
    (initial?.input?.receivers as { name: string; x: number; h?: number }[] | undefined)?.map((r) => ({ name: String(r.name), x: Number(r.x), h: Number(r.h ?? 1.5) })) ?? [{ name: "R1", x: 150, h: 1.5 }],
  );
  const [terrain, setTerrain] = useState<[number, number][]>(() =>
    req.terrain ? (req.terrain.x as number[]).map((x: number, i: number) => [x, (req.terrain.z as number[])[i]] as [number, number]) : [[0, 0], [100, 10], [200, 0]],
  );
  const [sx, setSx] = useState<number>(req.source_x ?? 0);
  const [sh, setSh] = useState<number>(req.source_h ?? 2);
  const [grid, setGrid] = useState(req.grid ?? { x0: 2, x1: 198, nx: 50, z0: 0, z1: 30, nz: 24 });
  const [limits, setLimits] = useState<string[]>(lim0.bands);
  const [weighting, setWeighting] = useState<"Z" | "A">(lim0.weighting);
  const [overallA, setOverallA] = useState(lim0.overallA);
  const [metric, setMetric] = useState<Metric>("bbA");
  const [res, setRes] = useState<Field2DResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const plot = useRef<HTMLDivElement>(null);

  const tx = terrain.map((p) => p[0]);
  const tz = terrain.map((p) => p[1]);
  const limitVec: Limits = useMemo(
    () => ({ bands: limits.map(num), weighting, overallA: num(overallA) }),
    [limits, weighting, overallA],
  );
  const hasLimits = limitVec.bands.some((b) => b != null) || limitVec.overallA != null;

  async function run(useCache = true) {
    setBusy(true);
    setErr(null);
    try {
      setRes(
        await runField2D(
          { Lw: lw, G, atm, mode, terrain: { x: tx, z: tz }, source_x: sx, source_h: sh, grid, limits: hasLimits ? limitVec : undefined, enclosure },
          useCache,
        ),
      );
      setSel(null);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  // A stored case runs once on opening so the map, colours and inspector are there immediately.
  useEffect(() => {
    if (pendingRun.current && ready) {
      pendingRun.current = false;
      void run();
    }
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps

  // values for the chosen metric, as an NZ x NX matrix
  const zmat = useMemo(() => {
    if (!res) return null;
    const NP = res.NX * res.NZ;
    const pick = (i: number): number | null => {
      if (!res.valid[i]) return null;
      if (metric === "bb") return res.Lp_broadband[i];
      if (metric === "bbA") return res.LpA_broadband[i];
      if (metric === "compliance") {
        const c = res.compliance?.code[i];
        return c == null || c < 0 ? null : c;
      }
      const [k, b] = metric.split(":");
      const band = parseInt(b, 10);
      if (k === "Lp") return res.Lp[i][band];
      if (k === "LpA") return res.LpA[i][band];
      if (k === "Abar") return res.Abar[i][band];
      return null;
    };
    const m: (number | null)[][] = [];
    for (let j = 0; j < res.NZ; j++) {
      const row: (number | null)[] = [];
      for (let i = 0; i < res.NX; i++) row.push(pick(j * res.NX + i));
      m.push(row);
    }
    return m.length === NP / res.NX ? m : null;
  }, [res, metric]);

  useEffect(() => {
    const el = plot.current;
    if (!el || !res || !zmat) return;
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim() || "#222";
    const grid_c = css.getPropertyValue("--line").trim() || "#ddd";
    const isC = metric === "compliance";
    const label = metric === "compliance" ? "Compliance" : metric === "bb" ? "L_p dB" : metric === "bbA" ? "L_p,A dB(A)" : "dB";
    const zmin = Math.min(...tz, grid.z0);
    const data: Plotly.Data[] = [
      isC
        ? ({
            type: "heatmap", x: res.x, y: res.z, z: zmat, zmin: 0, zmax: 1, showscale: false, hoverongaps: false,
            colorscale: [[0, "#b03030"], [0.5, "#b03030"], [0.5, "#2e8b57"], [1, "#2e8b57"]],
            hovertemplate: "x %{x:.1f} m, z %{y:.1f} m<extra></extra>",
          } as Plotly.Data)
        : ({
            type: "contour", x: res.x, y: res.z, z: zmat, connectgaps: false, hoverongaps: false,
            contours: { coloring: "heatmap", showlabels: true, labelfont: { size: 10, color: "#fff" } },
            line: { width: 0.6, color: "rgba(255,255,255,0.6)" },
            colorscale: "Viridis", reversescale: true, colorbar: { title: { text: label }, thickness: 12, len: 0.9 },
            hovertemplate: "x %{x:.1f} m, z %{y:.1f} m<br>%{z:.1f}<extra></extra>",
          } as Plotly.Data),
      { type: "scatter", mode: "lines", x: tx, y: tx.map(() => zmin - 1), line: { width: 0 }, hoverinfo: "skip", showlegend: false },
      { type: "scatter", mode: "lines", x: tx, y: tz, fill: "tonexty", fillcolor: "rgba(110,110,110,0.55)", line: { color: ink, width: 1.2 }, name: "Terrain", hoverinfo: "skip" },
      (() => {
        const g0 = groundAt(tx, tz, sx) ?? 0;
        return { type: "scatter", mode: "markers", x: [sx], y: [g0 + sh], marker: { symbol: "diamond", size: 10, color: ink, line: { color: "#fff", width: 1 } }, name: "Source", hoverinfo: "name" } as Plotly.Data;
      })(),
    ];
    if (sel != null && res.valid[sel]) {
      data.push({ type: "scatter", mode: "markers", x: [res.x[sel % res.NX]], y: [res.z[Math.floor(sel / res.NX)]], marker: { symbol: "circle-open", size: 12, color: ink, line: { width: 2 } }, name: "Selected", hoverinfo: "name" });
    }
    Plotly.react(
      el,
      data,
      {
        margin: { l: 52, r: 12, t: 8, b: 44 },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Inter, Segoe UI, sans-serif", size: 12, color: ink },
        xaxis: { title: { text: "Horizontal distance x, m" }, gridcolor: grid_c, range: [grid.x0, grid.x1] },
        yaxis: { title: { text: "Elevation z, m" }, gridcolor: grid_c, range: [Math.min(zmin, grid.z0), grid.z1] },
        showlegend: false,
      },
      { displayModeBar: false, responsive: true },
    );
    const any = el as unknown as { removeAllListeners?: (n: string) => void; on: (n: string, f: (e: Plotly.PlotMouseEvent) => void) => void };
    any.removeAllListeners?.("plotly_click");
    any.on("plotly_click", (ev) => {
      const p = ev.points[0];
      if (!p || p.x == null || p.y == null) return;
      const ix = res.x.reduce((b, v, i) => (Math.abs(v - Number(p.x)) < Math.abs(res.x[b] - Number(p.x)) ? i : b), 0);
      const iz = res.z.reduce((b, v, i) => (Math.abs(v - Number(p.y)) < Math.abs(res.z[b] - Number(p.y)) ? i : b), 0);
      setSel(iz * res.NX + ix);
    });
  }, [res, zmat, metric, sel, tx.join(), tz.join(), sx, sh, grid]); // eslint-disable-line react-hooks/exhaustive-deps

  const selInfo = useMemo(() => {
    if (!res || sel == null) return null;
    const ix = sel % res.NX;
    const iz = Math.floor(sel / res.NX);
    const c = res.compliance;
    return {
      x: res.x[ix], z: res.z[iz], valid: res.valid[sel],
      Lp: res.Lp[sel], LpA: res.LpA[sel], Abar: res.Abar[sel], Agr: res.Agr[sel],
      bb: res.Lp_broadband[sel], bbA: res.LpA_broadband[sel],
      kind: res.kind[sel],
      code: c?.code[sel] ?? null, margin: c?.margin[sel] ?? null, exceed: c?.exceed[sel] ?? null,
      worstBand: c?.worstBand[sel] ?? 0, worstMargin: c?.worstMargin[sel] ?? null,
      overallMargin: c?.overallMargin[sel] ?? null, overallExceed: c?.overallExceed[sel] ?? false,
    };
  }, [res, sel]);

  const metricOptions: [string, string][] = [
    ["bbA", "Broadband L_p,A (dB(A), 63-8000 Hz bands)"],
    ["bb", "Broadband L_p (dB, unweighted, 63-8000 Hz bands)"],
    ...(hasLimits ? ([["compliance", "Compliance: PASS green / FAIL red"]] as [string, string][]) : []),
    ...BANDS.map((f, i) => [`Lp:${i}`, `L_p ${f} Hz (unweighted)`] as [string, string]),
    ...BANDS.map((f, i) => [`LpA:${i}`, `L_p,A ${f} Hz (A-weighted)`] as [string, string]),
    ...BANDS.map((f, i) => [`Abar:${i}`, `A_bar ${f} Hz (screening)`] as [string, string]),
  ];
  const kindName = (k: number | null) => (k === 1 ? "line of sight blocked (taut-string path)" : k === 2 ? "clear, real crest below LOS (negative z)" : k === 0 ? "no relevant edge" : "n/a");
  const limArr = limitVec.bands;
  const predArr = selInfo ? (weighting === "A" ? selInfo.LpA : selInfo.Lp) : [];

  return (
    <div>
      <div className="scene">
        <div>
          <h2>Terrain profile (x, z in m)</h2>
          <div className="terrain">
            {terrain.map((p, i) => (
              <div key={i} className="trow">
                <input type="number" step={1} value={p[0]} onChange={(e) => setTerrain(terrain.map((q, j) => (j === i ? [parseFloat(e.target.value), q[1]] : q)))} />
                <input type="number" step={0.5} value={p[1]} onChange={(e) => setTerrain(terrain.map((q, j) => (j === i ? [q[0], parseFloat(e.target.value)] : q)))} />
                <button title="Delete vertex" disabled={terrain.length <= 2} onClick={() => setTerrain(terrain.filter((_, j) => j !== i))}>x</button>
              </div>
            ))}
            <button onClick={() => setTerrain([...terrain, [terrain[terrain.length - 1][0] + 20, terrain[terrain.length - 1][1]]])}>Add vertex</button>
          </div>
          <label className="field"><span>Source x</span><span className="inputwrap"><input type="number" value={sx} onChange={(e) => setSx(parseFloat(e.target.value))} /><em>m</em></span></label>
          <label className="field"><span>Source height above ground</span><span className="inputwrap"><input type="number" step={0.1} value={sh} onChange={(e) => setSh(parseFloat(e.target.value))} /><em>m</em></span></label>
          <h2>Named receivers (for saved cases)</h2>
          {rcv.map((q, i) => (
            <div key={i} className="trow">
              <input style={{ width: 90 }} value={q.name} onChange={(e) => setRcv(rcv.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))} aria-label="Receiver name" />
              <input type="number" title="x, m" value={q.x} onChange={(e) => setRcv(rcv.map((r, j) => (j === i ? { ...r, x: parseFloat(e.target.value) } : r)))} />
              <input type="number" title="height above ground, m" step={0.1} value={q.h} onChange={(e) => setRcv(rcv.map((r, j) => (j === i ? { ...r, h: parseFloat(e.target.value) } : r)))} />
              <button disabled={rcv.length <= 1} onClick={() => setRcv(rcv.filter((_, j) => j !== i))}>x</button>
            </div>
          ))}
          <button onClick={() => setRcv([...rcv, { name: `R${rcv.length + 1}`, x: 100, h: 1.5 }])}>Add receiver</button>
          <p className="note">Each row: name, x (m), height above ground (m).</p>
        </div>
        <div>
          <h2>Receiver grid</h2>
          {(["x0", "x1", "nx", "z0", "z1", "nz"] as const).map((k) => (
            <label key={k} className="field">
              <span>{k.startsWith("x") ? "x" : "z"} {k.endsWith("0") ? "min" : k.endsWith("1") ? "max" : "points"}</span>
              <span className="inputwrap"><input type="number" value={grid[k]} onChange={(e) => setGrid({ ...grid, [k]: parseFloat(e.target.value) })} /><em>{k.startsWith("n") ? "" : "m"}</em></span>
            </label>
          ))}
          <p className="note">z is absolute elevation. Points below the terrain are masked (no data). Cost is about 8 ms per point.</p>
        </div>
        <div>
          <h2>Permitted levels</h2>
          <label className="field"><span>Limits apply to</span>
            <select value={weighting} onChange={(e) => setWeighting(e.target.value as "Z" | "A")}>
              <option value="Z">unweighted octave-band L_p</option>
              <option value="A">A-weighted octave-band L_p,A</option>
            </select>
          </label>
          <div className="bands">
            {BANDS.map((f, i) => (
              <label key={f} className="band"><span>{f}</span>
                <input type="number" placeholder="none" value={limits[i]} onChange={(e) => setLimits(limits.map((v, j) => (j === i ? e.target.value : v)))} />
              </label>
            ))}
          </div>
          <label className="field"><span>Overall limit</span><span className="inputwrap"><input type="number" placeholder="none" value={overallA} onChange={(e) => setOverallA(e.target.value)} /><em>dB(A)</em></span></label>
          <p className="note">A point is PASS only if every band that has a limit is at or below it. Empty = no limit for that band.</p>
        </div>
      </div>

      <div className="tabs">
        <button className="primary" disabled={!ready || busy} onClick={() => run(true)}>{busy ? "Running" : "Run 2D section"}</button>
        <SaveCase
          kind="section"
          project={project ?? null}
          defaultName="Section case"
          editing={initial ? { id: initial.id, name: initial.name } : null}
          buildEdit={() => ({
            request: { Lw: lw, G, atm, mode, terrain: { x: tx, z: tz }, source_x: sx, source_h: sh, grid, limits: hasLimits ? limitVec : undefined, enclosure },
            receivers: rcv, run_field: true,
          })}
          build={() => ({
            request: { Lw: lw, G, atm, mode, terrain: { x: tx, z: tz }, source_x: sx, source_h: sh, grid, limits: hasLimits ? limitVec : undefined, enclosure },
            receivers: rcv, run_field: true,
          })}
        />
        <select value={metric} onChange={(e) => setMetric(e.target.value)}>
          {metricOptions.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {res && <span className="muted">{res._meta.cache_hit ? "cached" : `${res._meta.seconds.toFixed(1)} s`}</span>}
        {res && <button onClick={() => plot.current && void Plotly.downloadImage(plot.current, { format: "png", width: 1800, height: 900, scale: 2, filename: "noise-section-map" })}>Download PNG</button>}
      </div>
      {err && <div className="error">{err}</div>}
      <div ref={plot} style={{ width: "100%", height: 420 }} />
      {!res && <p className="muted">Run the section to see the field. Click any point on the map to inspect it.</p>}

      {selInfo && (
        <div className="inspector">
          <h2>Point x = {selInfo.x.toFixed(1)} m, z = {selInfo.z.toFixed(1)} m</h2>
          {!selInfo.valid ? (
            <p className="muted">No valid prediction here (inside the ground, at the source column, or outside the profile). This is not a PASS or a FAIL.</p>
          ) : (
            <>
              <p>
                {hasLimits && (
                  <strong className={selInfo.code === 1 ? "okc" : selInfo.code === 0 ? "badc" : "muted"}>
                    {selInfo.code === 1 ? "PASS" : selInfo.code === 0 ? "FAIL" : "NO DATA"}
                  </strong>
                )}{" "}
                Broadband L_p {fmt(selInfo.bb)} dB, L_p,A {fmt(selInfo.bbA)} dB(A) (63-8000 Hz bands). Path: {kindName(selInfo.kind)}.
                {selInfo.code === 0 && selInfo.worstBand > 0 && <> Worst exceedance {BANDS[selInfo.worstBand - 1]} Hz by {fmt(selInfo.worstMargin)} dB.</>}
                {selInfo.overallExceed && <> Overall dB(A) limit exceeded by {fmt(selInfo.overallMargin)} dB.</>}
              </p>
              <SpectrumChart
                predicted={predArr}
                label={weighting === "A" ? "L_p,A, dB(A)" : "L_p, dB"}
                limits={limArr}
                exceed={selInfo.exceed ?? undefined}
                height={240}
              />
              <table>
                <thead><tr><th>Hz</th><th>Permitted</th><th>Predicted</th><th>Margin</th><th>A_gr</th><th>A_bar</th></tr></thead>
                <tbody>
                  {BANDS.map((f, i) => (
                    <tr key={f} className={selInfo.exceed?.[i] ? "exc" : ""}>
                      <td>{f}</td>
                      <td>{limArr[i] == null ? "-" : limArr[i]!.toFixed(1)}</td>
                      <td>{fmt(predArr[i])}</td>
                      <td>{selInfo.margin?.[i] == null ? "-" : (selInfo.margin[i]! > 0 ? "+" : "") + selInfo.margin[i]!.toFixed(1)}</td>
                      <td>{fmt(selInfo.Agr[i], 2)}</td>
                      <td>{fmt(selInfo.Abar[i], 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note">Margin = predicted - permitted (positive = exceedance). Bands shown in red exceed their limit.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
