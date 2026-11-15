import { useCallback, useEffect, useMemo, useState } from "react";
import { A_WEIGHT, BANDS, CaseInput, CaseResult, CaseRow, Health, Mode, ProjectRow, getHealth, runCase } from "./api";
import { encFromRequest } from "./caseConvert";
import SpectrumChart from "./SpectrumChart";
import SectionView from "./SectionView";
import TerrainView from "./TerrainView";
import AudioView from "./AudioView";
import ProjectsView from "./ProjectsView";
import TestLabView from "./TestLabView";
import DiagnosticsView from "./DiagnosticsView";
import SaveCase from "./SaveCase";
import EnclosureEditor, { defaultEnc, toEnclosure } from "./EnclosureEditor";

type SourceKind = "LW" | "LWA";
type Scene = "point" | "section" | "terrain" | "audio" | "projects" | "testlab" | "diagnostics";

// Synthetic example only. It is NOT a measured or calibrated source.
const EXAMPLE_LW = [90, 95, 100, 100, 98, 95, 90, 85];

const fmt = (v: number, n = 1) => (Number.isFinite(v) ? v.toFixed(n) : "n/a");

function NumField(p: { label: string; unit: string; value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <label className="field">
      <span>{p.label}</span>
      <span className="inputwrap">
        <input type="number" step={p.step ?? 0.1} value={p.value} onChange={(e) => p.onChange(parseFloat(e.target.value))} />
        <em>{p.unit}</em>
      </span>
    </label>
  );
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);
  const [kind, setKind] = useState<SourceKind>("LW");
  const [bandsIn, setBandsIn] = useState<number[]>(EXAMPLE_LW);
  const [hs, setHs] = useState(2);
  const [hr, setHr] = useState(1.5);
  const [dp, setDp] = useState(150);
  const [G, setG] = useState({ Gs: 0.5, Gm: 0.5, Gr: 0.5 });
  const [atm, setAtm] = useState({ T_C: 10, RH: 70, p_kPa: 101.325 });
  const [mode, setMode] = useState<Mode>("iso2024");
  const [result, setResult] = useState<CaseResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"Z" | "A">("Z");
  const [scene, setScene] = useState<Scene>("point");
  const [enc, setEnc] = useState(defaultEnc());
  const [active, setActive] = useState<ProjectRow | null>(null);
  const [opened, setOpened] = useState<CaseRow | null>(null); // the stored case currently being edited, if any
  const [autoPoint, setAutoPoint] = useState(false);
  const encObj = useMemo(() => toEnclosure(enc), [enc]);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      getHealth()
        .then((h) => alive && (setHealth(h), setHealthErr(null)))
        .catch((e) => alive && setHealthErr(String(e)));
    tick();
    const id = setInterval(tick, 3000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Unweighted L_W actually sent to the solver.
  const lwUnweighted = useMemo(() => (kind === "LW" ? bandsIn : bandsIn.map((v, i) => v - A_WEIGHT[i])), [kind, bandsIn]);

  const run = useCallback(
    async (useCache = true) => {
      setBusy(true);
      setError(null);
      const c: CaseInput = { Lw: lwUnweighted, hs, hr, dp, G, atm, mode, enclosure: encObj };
      try {
        setResult(await runCase(c, useCache));
      } catch (e) {
        setError(String(e));
      } finally {
        setBusy(false);
      }
    },
    [lwUnweighted, hs, hr, dp, G, atm, mode, encObj],
  );

  // Open a stored case as if it had just been defined: restore the shared inputs here, then the view restores its own.
  function openCase(c: CaseRow) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const r = (c.input?.request ?? {}) as Record<string, any>;
    setKind("LW");
    setBandsIn((r.Lw as number[]) ?? bandsIn);
    if (r.G) setG(r.G);
    if (r.atm) setAtm(r.atm);
    setMode((r.mode as Mode) ?? "iso2024");
    setEnc(encFromRequest(r.enclosure));
    if (c.kind === "point") {
      setHs(r.hs);
      setHr(r.hr);
      setDp(r.dp);
      setResult(null);
      setAutoPoint(true);
    }
    setOpened(c);
    setScene(c.kind === "point" ? "point" : c.kind === "section" ? "section" : "terrain");
  }

  const ready = health?.matlab === "ready";
  useEffect(() => {
    if (autoPoint && ready) {
      setAutoPoint(false);
      void run(true);
    }
  }, [autoPoint, ready]); // eslint-disable-line react-hooks/exhaustive-deps
  const status = healthErr ? "API unreachable" : !health ? "connecting" : health.matlab === "ready" ? "MATLAB ready" : health.matlab;
  const series = result ? (view === "Z" ? result.Lp : result.LpA_bands) : [];

  return (
    <div className="app">
      <header className="topbar">
        <strong>Noise Box</strong>
        <span className="sep" />
        <select value={scene} onChange={(e) => setScene(e.target.value as Scene)} aria-label="Scene type">
          <option value="point">Flat ground, single receiver</option>
          <option value="section">2D vertical section (terrain)</option>
          <option value="terrain">3D terrain (DEM map)</option>
          <option value="audio">Source from a recording</option>
          <option value="projects">Projects and cases</option>
          <option value="testlab">Test Lab</option>
          <option value="diagnostics">MATLAB diagnostics</option>
        </select>
        <span className="grow" />
        <span className={`pill ${ready ? "ok" : "warn"}`}>{status}</span>
        <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} aria-label="Calculation standard">
          <option value="iso2024">ISO 9613-2:2024 (published)</option>
          <option value="draft2026">ISO 9613-2:2024 + DAmd 1 (DRAFT, experimental)</option>
          <option value="iso1996">ISO 9613-2:1996 compatibility (benchmarks only; 20 degC / 70 % RH)</option>
        </select>
        {scene === "point" && (
          <button className="primary" disabled={!ready || busy} onClick={() => run(true)}>
            {busy ? "Running" : "Run simulation"}
          </button>
        )}
      </header>

      <aside className="left">
        <h2>Source</h2>
        <label className="field">
          <span>Spectrum type</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as SourceKind)}>
            <option value="LW">Sound power level L_W, unweighted, dB re 1 pW</option>
            <option value="LWA">Sound power level L_W,A, A-weighted, dB re 1 pW</option>
          </select>
        </label>
        <p className="note">
          Sound power L_W describes what the source radiates and does not depend on distance. It is not a sound pressure level at 1 m.
          Sound pressure L_p is what a receiver would measure and depends on distance and propagation.
        </p>
        <div className="bands">
          {BANDS.map((f, i) => (
            <label key={f} className="band">
              <span>{f}</span>
              <input
                type="number"
                step={0.1}
                value={bandsIn[i]}
                onChange={(e) => setBandsIn(bandsIn.map((v, j) => (j === i ? parseFloat(e.target.value) : v)))}
              />
            </label>
          ))}
        </div>
        <p className="note">Bands in Hz; values in dB. Initial values are a synthetic example, not a measured or calibrated source.</p>

        <EnclosureEditor value={enc} onChange={setEnc} />

        <h2>Geometry</h2>
        <NumField label="Source height above ground" unit="m" value={hs} onChange={setHs} />
        <NumField label="Receiver height above ground" unit="m" value={hr} onChange={setHr} />
        <NumField label="Horizontal distance d_p" unit="m" value={dp} step={1} onChange={setDp} />

        <h2>Ground</h2>
        <NumField label="G source region" unit="0..1" value={G.Gs} step={0.05} onChange={(v) => setG({ ...G, Gs: v })} />
        <NumField label="G middle region" unit="0..1" value={G.Gm} step={0.05} onChange={(v) => setG({ ...G, Gm: v })} />
        <NumField label="G receiver region" unit="0..1" value={G.Gr} step={0.05} onChange={(v) => setG({ ...G, Gr: v })} />

        <h2>Atmosphere</h2>
        <NumField label="Temperature" unit="deg C" value={atm.T_C} onChange={(v) => setAtm({ ...atm, T_C: v })} />
        <NumField label="Relative humidity" unit="%" value={atm.RH} step={1} onChange={(v) => setAtm({ ...atm, RH: v })} />
        <NumField label="Pressure" unit="kPa" value={atm.p_kPa} onChange={(v) => setAtm({ ...atm, p_kPa: v })} />
      </aside>

      <main className="center">
        {scene === "section" && <SectionView key={`sec-${opened?.id ?? "new"}`} lw={lwUnweighted} G={G} atm={atm} mode={mode} ready={ready} enclosure={encObj} project={active} initial={opened?.kind === "section" ? opened : undefined} />}
        {scene === "projects" && <ProjectsView active={active} setActive={setActive} onOpen={openCase} />}
        {scene === "testlab" && <TestLabView active={active} />}
        {scene === "diagnostics" && <DiagnosticsView />}
        {scene === "audio" && (
          <AudioView
            G={G}
            atm={atm}
            onUse={(lw) => {
              setKind("LW");
              setBandsIn(lw.map((v) => Math.round(v * 10) / 10));
              setScene("point");
            }}
          />
        )}
        {scene === "terrain" && <TerrainView key={`ter-${opened?.id ?? "new"}`} lw={lwUnweighted} G={G} atm={atm} mode={mode} ready={ready} enclosure={encObj} project={active} initial={opened?.kind === "terrain" ? opened : undefined} />}
        {scene === "point" && (
          <div className="tabs">
            <SaveCase
              kind="point"
              project={active}
              defaultName="Flat ground case"
              editing={opened?.kind === "point" ? { id: opened.id, name: opened.name } : null}
              buildEdit={() => ({ request: { Lw: lwUnweighted, hs, hr, dp, G, atm, mode, enclosure: encObj }, receivers: [{ name: "R1" }] })}
              build={() => ({ request: { Lw: lwUnweighted, hs, hr, dp, G, atm, mode, enclosure: encObj }, receivers: [{ name: "R1" }] })}
            />
          </div>
        )}
        {scene === "point" && error && <div className="error">{error}</div>}
        {scene === "point" && !result && !error && <p className="muted pad">Set the inputs and run the simulation.</p>}
        {scene === "point" && result && (
          <>
            <div className="tabs">
              <button className={view === "Z" ? "on" : ""} onClick={() => setView("Z")}>Unweighted L_p</button>
              <button className={view === "A" ? "on" : ""} onClick={() => setView("A")}>A-weighted L_p,A</button>
            </div>
            <SpectrumChart predicted={series} label={view === "Z" ? "L_p, dB re 20 uPa (unweighted)" : "L_p,A, dB(A)"} />
            <table>
              <thead>
                <tr>
                  <th>Hz</th>
                  <th>L_W</th>
                  <th>A_div</th>
                  <th>A_atm</th>
                  <th>A_gr</th>
                  <th>A_bar</th>
                  <th>A_total</th>
                  <th>L_p</th>
                  <th>L_p,A</th>
                </tr>
              </thead>
              <tbody>
                {BANDS.map((f, i) => (
                  <tr key={f}>
                    <td>{f}</td>
                    <td>{fmt(result.Lw[i])}</td>
                    <td>{fmt(result.Adiv[i])}</td>
                    <td>{fmt(result.Aatm[i], 2)}</td>
                    <td>{fmt(result.Agr[i], 2)}</td>
                    <td>{fmt(result.Abar[i], 2)}</td>
                    <td>{fmt(result.Atotal[i], 2)}</td>
                    <td>{fmt(result.Lp[i])}</td>
                    <td>{fmt(result.LpA_bands[i])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="note">All terms in dB. A_gr may be negative; it is not clamped. L_p = L_W + D_c - A (ISO 9613-2:2024 Formula 3), D_c = 0 here.</p>
          </>
        )}
      </main>

      <aside className="right">
        <h2>Result</h2>
        {result ? (
          <dl>
            <dt>Standard</dt>
            <dd>{result.mode === "iso2024" ? "ISO 9613-2:2024" : "ISO 9613-2:2024 + DAmd 1 (DRAFT)"}</dd>
            <dt>Distance d (3D)</dt>
            <dd>{fmt(result.d, 2)} m</dd>
            <dt>Broadband L_p, 63-8000 Hz bands</dt>
            <dd>{fmt(result.Lp_broadband)} dB (unweighted)</dd>
            <dt>Broadband L_p,A, 63-8000 Hz bands</dt>
            <dd>{fmt(result.LpA_broadband)} dB(A)</dd>
            <dt>C_met</dt>
            <dd>{fmt(result.Cmet)} dB (not applied)</dd>
          </dl>
        ) : (
          <p className="muted">No result yet.</p>
        )}
        {result?.enclosure && (
          <>
            <h2>Enclosure effect</h2>
            <table>
              <thead><tr><th>Hz</th><th>L_W in</th><th>L_W out</th></tr></thead>
              <tbody>
                {BANDS.map((f, i) => (
                  <tr key={f} className={result.enclosure!.notApplicableBands[i] ? "exc" : ""}>
                    <td>{f}</td><td>{fmt(result.enclosure!.Lw_in[i])}</td><td>{fmt(result.enclosure!.Lw_out[i])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="note">{(Array.isArray(result.enclosure.warnings) ? result.enclosure.warnings : [result.enclosure.warnings]).map((w) => <li key={w}>{w}</li>)}</ul>
          </>
        )}
        {result && (
          <>
            <h2>Run record</h2>
            <dl>
              <dt>Cache</dt>
              <dd>{result._meta.cache_hit ? "hit (same inputs and code)" : "computed"}</dd>
              <dt>MATLAB code reloaded</dt>
              <dd>{result._meta.reloaded ? "yes, files changed" : "no"}</dd>
              <dt>Time</dt>
              <dd>{result._meta.seconds} s</dd>
            </dl>
            <button onClick={() => run(false)} disabled={busy}>Recompute without cache</button>
            <h2>Not modelled</h2>
            <ul className="note">
              {result.notImplemented.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </>
        )}
        {health && (
          <>
            <h2>MATLAB library</h2>
            <p className="note mono">{health.library}</p>
            <p className="note">
              Runs {health.stats.runs}, cache hits {health.stats.cache_hits}, reloads {health.stats.reloads}
            </p>
          </>
        )}
      </aside>
    </div>
  );
}
