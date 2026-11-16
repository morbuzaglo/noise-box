import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import EnclosureEditor, { EncState, defaultEnc, toEnclosure } from "./EnclosureEditor";
import Palette, { Command, collectParams } from "./Palette";
import { DialogHost, Toasts, confirmDialog, promptDialog, toast } from "./ui";
import {
  IconAudio, IconDiag, IconLab, IconLogo, IconMoon, IconPanelLeft, IconPanelRight, IconPlay, IconPoint, IconPreset, IconProjects,
  IconRedo, IconReset, IconSearch, IconSection, IconSun, IconTerrain, IconUndo,
} from "./icons";

type SourceKind = "LW" | "LWA";
type Scene = "point" | "section" | "terrain" | "audio" | "projects" | "testlab" | "diagnostics";

// Synthetic example only. It is NOT a measured or calibrated source.
const EXAMPLE_LW = [90, 95, 100, 100, 98, 95, 90, 85];
const DEF = { hs: 2, hr: 1.5, dp: 150, G: { Gs: 0.5, Gm: 0.5, Gr: 0.5 }, atm: { T_C: 10, RH: 70, p_kPa: 101.325 } };

const SCENES: { id: Scene; label: string; title: string; icon: ReactNode }[] = [
  { id: "point", label: "Point", title: "Flat ground, single receiver", icon: <IconPoint /> },
  { id: "section", label: "Section", title: "2D vertical section (terrain)", icon: <IconSection /> },
  { id: "terrain", label: "Terrain", title: "3D terrain (DEM map)", icon: <IconTerrain /> },
  { id: "audio", label: "Audio", title: "Source from a recording", icon: <IconAudio /> },
  { id: "projects", label: "Projects", title: "Projects and cases", icon: <IconProjects /> },
  { id: "testlab", label: "Test Lab", title: "Test Lab", icon: <IconLab /> },
  { id: "diagnostics", label: "MATLAB", title: "MATLAB diagnostics", icon: <IconDiag /> },
];

const fmt = (v: number, n = 1) => (Number.isFinite(v) ? v.toFixed(n) : "n/a");

// A parameter field. `def` (optional) is the documented default: an edited value is marked and can be reset.
function NumField(p: { label: string; unit: string; value: number; onChange: (v: number) => void; step?: number; def?: number; min?: number; max?: number }) {
  const edited = p.def !== undefined && p.value !== p.def;
  const bad = !Number.isFinite(p.value) || (p.min !== undefined && p.value < p.min) || (p.max !== undefined && p.value > p.max);
  return (
    <label className={`field${edited ? " edited" : ""}`} title={p.def !== undefined ? `Default ${p.def} ${p.unit}` : undefined}>
      <span>{p.label}</span>
      <span className="inputwrap">
        <input type="number" step={p.step ?? 0.1} min={p.min} max={p.max} aria-invalid={bad} value={p.value} onChange={(e) => p.onChange(parseFloat(e.target.value))} />
        <em>{p.unit}</em>
        {p.def !== undefined && (
          <button type="button" className="reset icon" aria-label={`Reset ${p.label} to ${p.def}`} title={`Reset to ${p.def}`} onClick={() => p.onChange(p.def as number)}><IconReset /></button>
        )}
      </span>
    </label>
  );
}

function Sec(p: { title: string; children: ReactNode; open?: boolean; edited?: number }) {
  return (
    <details className="sec" open={p.open ?? true}>
      <summary>{p.title}{p.edited ? <span className="count">{p.edited} edited</span> : null}</summary>
      <div className="sec-body">{p.children}</div>
    </details>
  );
}

// ---- shared parameter snapshot: undo/redo and presets operate on exactly the inputs sent to the solver ----
interface Snap {
  kind: SourceKind; bandsIn: number[]; hs: number; hr: number; dp: number;
  G: { Gs: number; Gm: number; Gr: number }; atm: { T_C: number; RH: number; p_kPa: number }; mode: Mode; enc: EncState;
}
const store = {
  get<T>(k: string, d: T): T { try { const v = localStorage.getItem(k); return v ? (JSON.parse(v) as T) : d; } catch { return d; } },
  set(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable: layout simply is not remembered */ } },
};
type Theme = "system" | "light" | "dark";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);
  const [kind, setKind] = useState<SourceKind>("LW");
  const [bandsIn, setBandsIn] = useState<number[]>(EXAMPLE_LW);
  const [hs, setHs] = useState(DEF.hs);
  const [hr, setHr] = useState(DEF.hr);
  const [dp, setDp] = useState(DEF.dp);
  const [G, setG] = useState(DEF.G);
  const [atm, setAtm] = useState(DEF.atm);
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

  // ---- workbench state (presentation only) ----
  const [theme, setTheme] = useState<Theme>(() => store.get<Theme>("nb.theme", "system"));
  const [layout, setLayout] = useState(() => store.get("nb.layout", { lw: 300, rw: 280, lo: true, ro: true }));
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [presets, setPresets] = useState<Record<string, Snap>>(() => store.get("nb.presets", {}));
  const [presetSel, setPresetSel] = useState("");
  const leftRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = document.documentElement;
    if (theme === "system") el.removeAttribute("data-theme");
    else el.setAttribute("data-theme", theme);
    store.set("nb.theme", theme);
  }, [theme]);
  useEffect(() => store.set("nb.layout", layout), [layout]);
  const isDark = theme === "dark" || (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);

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
        toast("Calculation failed. See the message above the results.", "bad");
      } finally {
        setBusy(false);
      }
    },
    [lwUnweighted, hs, hr, dp, G, atm, mode, encObj],
  );

  // ---- undo / redo of the shared parameters (debounced snapshots) ----
  const snap: Snap = useMemo(() => ({ kind, bandsIn, hs, hr, dp, G, atm, mode, enc }), [kind, bandsIn, hs, hr, dp, G, atm, mode, enc]);
  const hist = useRef<{ stack: Snap[]; i: number }>({ stack: [snap], i: 0 });
  const [, bump] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => {
      const h = hist.current;
      if (JSON.stringify(h.stack[h.i]) === JSON.stringify(snap)) return;
      h.stack = h.stack.slice(0, h.i + 1).concat([snap]).slice(-60);
      h.i = h.stack.length - 1;
      bump((n) => n + 1);
    }, 450);
    return () => clearTimeout(t);
  }, [snap]);
  const restore = useCallback((s: Snap) => {
    setKind(s.kind); setBandsIn(s.bandsIn); setHs(s.hs); setHr(s.hr); setDp(s.dp); setG(s.G); setAtm(s.atm); setMode(s.mode); setEnc(s.enc);
  }, []);
  const step = useCallback((d: -1 | 1) => {
    const h = hist.current;
    const ni = h.i + d;
    if (ni < 0 || ni >= h.stack.length) return;
    h.i = ni;
    restore(h.stack[ni]);
    bump((n) => n + 1);
  }, [restore]);
  const canUndo = hist.current.i > 0;
  const canRedo = hist.current.i < hist.current.stack.length - 1;

  // ---- presets (saved in this browser; they hold the shared parameters only, not terrain, obstacles or receivers) ----
  async function savePreset() {
    const name = (await promptDialog("Save parameter preset", "Stores source spectrum, enclosure, geometry, ground, atmosphere and standard. Terrain, obstacles and receivers belong to cases.", ""))?.trim();
    if (!name) return;
    if (presets[name] && !(await confirmDialog("Replace preset", `A preset named "${name}" exists. Replace it?`))) return;
    const next = { ...presets, [name]: snap };
    setPresets(next); store.set("nb.presets", next); setPresetSel(name);
    toast(`Preset "${name}" saved`, "ok");
  }
  async function deletePreset() {
    if (!presetSel || !(await confirmDialog("Delete preset", `Delete preset "${presetSel}"?`))) return;
    const { [presetSel]: _gone, ...rest } = presets;
    setPresets(rest); store.set("nb.presets", rest); setPresetSel("");
  }

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

  // ---- CSV export of the band table (values exactly as returned by the solver) ----
  function exportCsv() {
    if (!result) return;
    const head = ["Hz", "L_W", "A_div", "A_atm", "A_gr", "A_bar", "A_total", "L_p", "L_p,A"];
    const rows = BANDS.map((f, i) => [f, result.Lw[i], result.Adiv[i], result.Aatm[i], result.Agr[i], result.Abar[i], result.Atotal[i], result.Lp[i], result.LpA_bands[i]]);
    const csv = [head, ...rows].map((r) => r.join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "noise-box-point-result.csv";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("Band table exported", "ok");
  }

  // ---- keyboard shortcuts ----
  const sceneRef = useRef(scene);
  sceneRef.current = scene;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen(true); }
      else if (mod && e.key === "Enter" && sceneRef.current === "point" && ready && !busy) { e.preventDefault(); void run(true); }
      else if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); setLayout((l) => (e.shiftKey ? { ...l, ro: !l.ro } : { ...l, lo: !l.lo })); }
      else if (mod && !typing && e.key.toLowerCase() === "z") { e.preventDefault(); step(e.shiftKey ? 1 : -1); }
      else if (mod && !typing && e.key.toLowerCase() === "y") { e.preventDefault(); step(1); }
      else if (e.altKey && /^[1-7]$/.test(e.key)) { e.preventDefault(); setScene(SCENES[Number(e.key) - 1].id); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ready, busy, run, step]);

  // ---- resizable side panels ----
  function startDrag(side: "l" | "r") {
    return (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      const el = e.currentTarget;
      el.classList.add("drag");
      const move = (ev: PointerEvent) =>
        setLayout((l) => (side === "l" ? { ...l, lw: Math.max(220, Math.min(560, ev.clientX - 52)) } : { ...l, rw: Math.max(200, Math.min(520, window.innerWidth - ev.clientX)) }));
      const up = () => { el.classList.remove("drag"); window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    };
  }

  const commands: Command[] = useMemo(() => {
    if (!paletteOpen) return [];
    const go = SCENES.map((s, i): Command => ({ id: `scene-${s.id}`, label: `Go to: ${s.title}`, group: "Views", hint: `Alt+${i + 1}`, run: () => setScene(s.id) }));
    const acts: Command[] = [
      { id: "run", label: "Run simulation (flat ground)", group: "Actions", hint: "Ctrl+Enter", run: () => { setScene("point"); void run(true); } },
      { id: "undo", label: "Undo parameter change", group: "Actions", hint: "Ctrl+Z", run: () => step(-1) },
      { id: "redo", label: "Redo parameter change", group: "Actions", hint: "Ctrl+Shift+Z", run: () => step(1) },
      { id: "left", label: "Toggle parameter panel", group: "Actions", hint: "Ctrl+B", run: () => setLayout((l) => ({ ...l, lo: !l.lo })) },
      { id: "right", label: "Toggle results panel", group: "Actions", hint: "Ctrl+Shift+B", run: () => setLayout((l) => ({ ...l, ro: !l.ro })) },
      { id: "theme", label: `Switch to ${isDark ? "light" : "dark"} theme`, group: "Actions", run: () => setTheme(isDark ? "light" : "dark") },
      { id: "preset", label: "Save current parameters as preset", group: "Actions", run: () => void savePreset() },
    ];
    return [...go, ...acts, ...collectParams(leftRef.current)];
  }, [paletteOpen]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (paletteOpen && !layout.lo) setLayout((l) => ({ ...l, lo: true })); // parameter search needs the panel visible
  }, [paletteOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const sceneInfo = SCENES.find((s) => s.id === scene)!;
  const dotCls = healthErr ? "bad" : ready ? "ok" : "";
  const modeLabel = mode === "iso2024" ? "ISO 9613-2:2024" : mode === "draft2026" ? "ISO 9613-2:2024 + DAmd 1 (DRAFT)" : "ISO 9613-2:1996 compatibility";
  const nGeo = [hs !== DEF.hs, hr !== DEF.hr, dp !== DEF.dp].filter(Boolean).length;
  const nGround = [G.Gs !== DEF.G.Gs, G.Gm !== DEF.G.Gm, G.Gr !== DEF.G.Gr].filter(Boolean).length;
  const nAtm = [atm.T_C !== DEF.atm.T_C, atm.RH !== DEF.atm.RH, atm.p_kPa !== DEF.atm.p_kPa].filter(Boolean).length;
  const nBands = bandsIn.filter((v, i) => v !== EXAMPLE_LW[i]).length;

  return (
    <div className={`app${layout.lo ? "" : " no-left"}${layout.ro ? "" : " no-right"}`} style={{ ["--left-w" as string]: `${layout.lw}px`, ["--right-w" as string]: `${layout.rw}px` }}>
      <header className="topbar">
        <span className="brand"><IconLogo />Noise Box</span>
        <span className="sep" />
        <span className="crumbs"><b>{sceneInfo.title}</b>{active ? ` · ${active.name}` : ""}{opened ? ` · case "${opened.name}"` : ""}</span>
        <span className="grow" />
        <button className="icon ghost" aria-label="Undo parameter change (Ctrl+Z)" title="Undo (Ctrl+Z)" disabled={!canUndo} onClick={() => step(-1)}><IconUndo /></button>
        <button className="icon ghost" aria-label="Redo parameter change (Ctrl+Shift+Z)" title="Redo (Ctrl+Shift+Z)" disabled={!canRedo} onClick={() => step(1)}><IconRedo /></button>
        <span className="sep" />
        <button className="ghost" onClick={() => setPaletteOpen(true)} title="Search parameters, views and actions"><IconSearch />Search <kbd>Ctrl K</kbd></button>
        <button className="icon ghost" aria-label="Toggle parameter panel (Ctrl+B)" title="Parameter panel (Ctrl+B)" aria-pressed={layout.lo} onClick={() => setLayout({ ...layout, lo: !layout.lo })}><IconPanelLeft /></button>
        <button className="icon ghost" aria-label="Toggle results panel (Ctrl+Shift+B)" title="Results panel (Ctrl+Shift+B)" aria-pressed={layout.ro} onClick={() => setLayout({ ...layout, ro: !layout.ro })}><IconPanelRight /></button>
        <button className="icon ghost" aria-label={`Switch to ${isDark ? "light" : "dark"} theme`} title="Theme" onClick={() => setTheme(isDark ? "light" : "dark")}>{isDark ? <IconSun /> : <IconMoon />}</button>
        <span className="sep" />
        <span className={`pill ${ready ? "ok" : healthErr ? "bad" : "warn"}`}>{status}</span>
        <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} aria-label="Calculation standard">
          <option value="iso2024">ISO 9613-2:2024 (published)</option>
          <option value="draft2026">ISO 9613-2:2024 + DAmd 1 (DRAFT, experimental)</option>
          <option value="iso1996">ISO 9613-2:1996 compatibility (benchmarks only; 20 degC / 70 % RH)</option>
        </select>
        {scene === "point" && (
          <button className="primary" disabled={!ready || busy} onClick={() => run(true)} title="Run simulation (Ctrl+Enter)">
            <IconPlay />{busy ? "Running" : "Run simulation"}
          </button>
        )}
      </header>

      <nav className="rail" aria-label="Views">
        {SCENES.map((s, i) => (
          <button key={s.id} aria-current={scene === s.id ? "page" : undefined} title={`${s.title} (Alt+${i + 1})`} onClick={() => setScene(s.id)}>
            {s.icon}<span>{s.label}</span>
          </button>
        ))}
      </nav>

      <aside className="left" ref={leftRef} aria-label="Model parameters">
        <div className="panel-head">
          <IconPreset />
          <select value={presetSel} aria-label="Parameter presets" onChange={(e) => { setPresetSel(e.target.value); if (presets[e.target.value]) { restore(presets[e.target.value]); toast(`Preset "${e.target.value}" loaded`, "ok"); } }} style={{ flex: 1, minWidth: 0 }}>
            <option value="">{Object.keys(presets).length ? "Load preset..." : "No presets yet"}</option>
            {Object.keys(presets).map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <button onClick={() => void savePreset()} title="Save the current shared parameters as a preset">Save</button>
          <button disabled={!presetSel} onClick={() => void deletePreset()}>Delete</button>
        </div>

        <Sec title="Source" edited={nBands + (kind !== "LW" ? 1 : 0)}>
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
              <label key={f} className={`band${bandsIn[i] !== EXAMPLE_LW[i] ? " edited" : ""}`}>
                <span>{f}</span>
                <input
                  type="number"
                  step={0.1}
                  aria-invalid={!Number.isFinite(bandsIn[i])}
                  value={bandsIn[i]}
                  onChange={(e) => setBandsIn(bandsIn.map((v, j) => (j === i ? parseFloat(e.target.value) : v)))}
                />
              </label>
            ))}
          </div>
          <p className="note">Bands in Hz; values in dB. Initial values are a synthetic example, not a measured or calibrated source. A highlighted band differs from that example.</p>
        </Sec>

        <Sec title="Source enclosure (optional)" open={enc.on}>
          <EnclosureEditor value={enc} onChange={setEnc} />
        </Sec>

        <Sec title="Geometry" edited={nGeo}>
          <NumField label="Source height above ground" unit="m" value={hs} def={DEF.hs} onChange={setHs} />
          <NumField label="Receiver height above ground" unit="m" value={hr} def={DEF.hr} onChange={setHr} />
          <NumField label="Horizontal distance d_p" unit="m" value={dp} def={DEF.dp} step={1} onChange={setDp} />
        </Sec>

        <Sec title="Ground" edited={nGround}>
          <NumField label="G source region" unit="0..1" value={G.Gs} def={DEF.G.Gs} min={0} max={1} step={0.05} onChange={(v) => setG({ ...G, Gs: v })} />
          <NumField label="G middle region" unit="0..1" value={G.Gm} def={DEF.G.Gm} min={0} max={1} step={0.05} onChange={(v) => setG({ ...G, Gm: v })} />
          <NumField label="G receiver region" unit="0..1" value={G.Gr} def={DEF.G.Gr} min={0} max={1} step={0.05} onChange={(v) => setG({ ...G, Gr: v })} />
          <p className="note">G = 0 hard ground, G = 1 porous ground.</p>
        </Sec>

        <Sec title="Atmosphere" edited={nAtm}>
          <NumField label="Temperature" unit="deg C" value={atm.T_C} def={DEF.atm.T_C} onChange={(v) => setAtm({ ...atm, T_C: v })} />
          <NumField label="Relative humidity" unit="%" value={atm.RH} def={DEF.atm.RH} min={0} max={100} step={1} onChange={(v) => setAtm({ ...atm, RH: v })} />
          <NumField label="Pressure" unit="kPa" value={atm.p_kPa} def={DEF.atm.p_kPa} onChange={(v) => setAtm({ ...atm, p_kPa: v })} />
        </Sec>
      </aside>
      <div className="lsplit" role="separator" aria-orientation="vertical" aria-label="Resize parameter panel" onPointerDown={startDrag("l")} />

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
            {result && <button onClick={exportCsv}>Export band table (CSV)</button>}
          </div>
        )}
        {scene === "point" && error && <div className="error">{error}</div>}
        {scene === "point" && !result && !error && (
          <div className="empty"><b>No result yet</b>Set the source, geometry, ground and atmosphere in the left panel, then press Run simulation (Ctrl+Enter).</div>
        )}
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
      <div className="rsplit" role="separator" aria-orientation="vertical" aria-label="Resize results panel" onPointerDown={startDrag("r")} />

      <aside className="right" aria-label="Results summary">
        {scene !== "point" && <p className="note">Results of this view are shown in the view itself. This panel summarises the flat-ground point calculation.</p>}
        <h2>Result (flat ground)</h2>
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
            <p><button onClick={() => run(false)} disabled={busy}>Recompute without cache</button></p>
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

      <footer className="statusbar">
        <span><i className={`dot ${dotCls}`} />{status}</span>
        <span>{modeLabel}</span>
        <span>Project: {active ? active.name : "none"}</span>
        {opened && <span>Case: {opened.name}</span>}
        <span className="grow" />
        {health && <span>Runs {health.stats.runs} · cache hits {health.stats.cache_hits} · reloads {health.stats.reloads}</span>}
        <span><kbd>Ctrl K</kbd> search</span>
      </footer>

      {paletteOpen && <Palette commands={commands} onClose={() => setPaletteOpen(false)} />}
      <DialogHost />
      <Toasts />
    </div>
  );
}
