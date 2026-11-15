import { useEffect, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { BANDS, Case3DResult, CaseRow, DemInfo, EnclosureIn, DemSurface, Field3DResult, GroundAreaIn, Mode, ObstacleIn, getDemSurface, restoreCaseDem, runCase3D, runField3D, syntheticDem, uploadDem } from "./api";
import { limFromRequest } from "./caseConvert";
import LimitsEditor, { LimitState, defaultLimits, hasAnyLimit, toLimits } from "./LimitsEditor";
import PointInspector, { PointData } from "./PointInspector";
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
  initial?: CaseRow; // a stored case to open as if it had just been defined here
}

type Metric = string;
type Tab = "map" | "3d";
const nearest = (arr: number[], v: number) => arr.reduce((b, x, i) => (Math.abs(x - v) < Math.abs(arr[b] - v) ? i : b), 0);

// Editable obstacle rows. A wall is a thin centre line (one diffracting edge); a building is a rectangle footprint;
// a polygon is any footprint given as "x y" lines (needed for the ISO/TR 17534-3 buildings).
// Optional fabric: sound ALSO transmits through the material (engineering approximation, reported separately).
interface Fab { on: boolean; mode: "mass" | "tl"; mass: number; tl: string[]; open: number }
type ObsRow = (
  | { kind: "wall"; x1: number; y1: number; x2: number; y2: number; h: number }
  | { kind: "building"; x0: number; x1: number; y0: number; y1: number; h: number }
  | { kind: "polygon"; pts: string; h: number }
) & { gap: number; fab: Fab };
interface AreaRow { pts: string; G: number }

const newFab = (): Fab => ({ on: false, mode: "mass", mass: 0.4, tl: ["8", "10", "12", "14", "16", "18", "20", "22"], open: 0 });

function parsePts(t: string): { x: number[]; y: number[] } {
  const pts = t.split(/[\n;]+/).map((l) => l.trim().split(/[\s,]+/).map(parseFloat)).filter((p) => p.length >= 2 && p.every(Number.isFinite));
  return { x: pts.map((p) => p[0]), y: pts.map((p) => p[1]) };
}
const ptsText = (x: number[], y: number[]) => x.map((v, i) => `${v} ${y[i]}`).join("\n");

function toObstacle(o: ObsRow): ObstacleIn {
  let base: ObstacleIn;
  if (o.kind === "wall") base = { kind: "wall", x: [o.x1, o.x2], y: [o.y1, o.y2], h: o.h };
  else if (o.kind === "building") base = { kind: "building", x: [o.x0, o.x1, o.x1, o.x0], y: [o.y0, o.y0, o.y1, o.y1], h: o.h };
  else {
    const q = parsePts(o.pts);
    base = { kind: q.x.length === 2 ? "wall" : "building", x: q.x, y: q.y, h: o.h };
  }
  if (o.gap > 0) base.gap = o.gap;
  if (o.fab.on) {
    base.material = o.fab.mode === "mass" ? { surface_mass: o.fab.mass, openness: o.fab.open } : { TL: o.fab.tl.map(parseFloat), openness: o.fab.open };
  }
  return base;
}

// Stored obstacle -> editor row (the exact inverse of toObstacle for walls and rectangles; anything else becomes a polygon).
function fromObstacle(o: ObstacleIn): ObsRow {
  const fab = newFab();
  if (o.material) {
    fab.on = true;
    fab.open = o.material.openness ?? 0;
    if (o.material.TL) { fab.mode = "tl"; fab.tl = o.material.TL.map(String); } else { fab.mode = "mass"; fab.mass = o.material.surface_mass ?? 0.4; }
  }
  const common = { gap: o.gap ?? 0, fab };
  if (o.x.length === 2) return { kind: "wall", x1: o.x[0], y1: o.y[0], x2: o.x[1], y2: o.y[1], h: o.h, ...common };
  const rect = o.x.length === 4 && o.x[0] === o.x[3] && o.x[1] === o.x[2] && o.y[0] === o.y[1] && o.y[2] === o.y[3];
  if (rect) return { kind: "building", x0: o.x[0], x1: o.x[1], y0: o.y[0], y1: o.y[2], h: o.h, ...common };
  return { kind: "polygon", pts: ptsText(o.x, o.y), h: o.h, ...common };
}

const asRows = (v: number[] | number[][] | undefined): number[][] => (Array.isArray(v) && Array.isArray(v[0]) ? (v as number[][]) : []);
const asArr = (v: number | number[] | undefined): number[] => (v == null ? [] : Array.isArray(v) ? v : [v]);
const f2 = (v: number | undefined | null, n = 2) => (v == null || !Number.isFinite(v) ? "-" : v.toFixed(n));

export default function TerrainView({ lw, G, atm, mode, ready, enclosure, project, initial }: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const req = (initial?.input?.request ?? {}) as Record<string, any>;
  const [rcv, setRcv] = useState<{ name: string; x: number; y: number; h: number }[]>(() =>
    (initial?.input?.receivers as { name: string; x: number; y: number; h?: number }[] | undefined)?.map((r) => ({ name: String(r.name), x: Number(r.x), y: Number(r.y), h: Number(r.h ?? 1.5) })) ?? [{ name: "R1", x: 200, y: 150, h: 1.5 }],
  );
  const [areas, setAreas] = useState<AreaRow[]>(() => ((req.ground_areas ?? []) as GroundAreaIn[]).map((a) => ({ pts: ptsText(a.x, a.y), G: a.G })));
  const [gDefault, setGDefault] = useState<string>(req.ground_default != null ? String(req.ground_default) : "");
  const [gMethod, setGMethod] = useState<"general" | "simplified">(req.ground_method ?? "general");
  const pendingRun = useRef(!!initial);
  const [dem, setDem] = useState<DemInfo | null>(null);
  const [surf, setSurf] = useState<DemSurface | null>(null);
  const [src, setSrc] = useState(req.source ? { x: Number(req.source.x), y: Number(req.source.y), h: Number(req.source.h) } : { x: 20, y: 150, h: 2 });
  const [hr, setHr] = useState<number>(req.hr ?? 1.5);
  const [gridN, setGridN] = useState({ nx: Number(req.grid?.nx ?? 40), ny: Number(req.grid?.ny ?? 40) });
  const [lim, setLim] = useState<LimitState>(initial ? limFromRequest(req.limits) : defaultLimits());
  const [metric, setMetric] = useState<Metric>("bbA");
  const [tab, setTab] = useState<Tab>("map");
  const [clickMode, setClickMode] = useState<"inspect" | "source">("inspect");
  const [res, setRes] = useState<Field3DResult | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [unit, setUnit] = useState("m");
  const [metricDecl, setMetricDecl] = useState(false);
  const [obstacles, setObstacles] = useState<ObsRow[]>(() => ((req.obstacles ?? []) as ObstacleIn[]).map(fromObstacle));
  const [pathInfo, setPathInfo] = useState<Case3DResult | null>(null);
  const [pathBusy, setPathBusy] = useState(false);
  const mapRef = useRef<HTMLDivElement>(null);
  const d3Ref = useRef<HTMLDivElement>(null);

  const limits = useMemo(() => toLimits(lim), [lim]);
  const hasLimits = hasAnyLimit(limits);

  // Ground areas / method as the API expects them (shared by the map run, the path inspector and "Save as case").
  const groundExtras = () => {
    const ga: GroundAreaIn[] = areas.map((a) => ({ ...parsePts(a.pts), G: a.G })).filter((a) => a.x.length >= 3);
    const out: { ground_areas?: GroundAreaIn[]; ground_default?: number; ground_method?: "general" | "simplified" } = {};
    if (ga.length) out.ground_areas = ga;
    if (gDefault.trim() !== "") out.ground_default = parseFloat(gDefault);
    if (gMethod !== "general") out.ground_method = gMethod;
    return out;
  };

  // Opening a stored case: bring back its DEM, then run it once so the map, colours and paths are there.
  useEffect(() => {
    if (initial) restoreCaseDem(initial.id).then((info) => adopt(info, true)).catch((e) => setErr(String(e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (dem && pendingRun.current) {
      pendingRun.current = false;
      void run();
    }
  }, [dem]); // eslint-disable-line react-hooks/exhaustive-deps

  async function adopt(info: DemInfo, keepScene = false) {
    setDem(info);
    setRes(null);
    setSel(null);
    const ext = { x: info.cs * (info.nx - 1), y: info.cs * (info.ny - 1) };
    if (!keepScene) setSrc({ x: Math.round(info.x0 + 0.1 * ext.x), y: Math.round(info.y0 + 0.5 * ext.y), h: 2 });
    setSurf(await getDemSurface(info.dem_id, Math.max(1, Math.ceil(Math.max(info.nx, info.ny) / 120))));
  }

  async function load(fn: () => Promise<DemInfo>) {
    setErr(null);
    try {
      await adopt(await fn());
    } catch (e) {
      setErr(String(e));
    }
  }

  async function run(useCache = true) {
    if (!dem) return;
    setBusy(true);
    setErr(null);
    try {
      const x1 = dem.x0 + dem.cs * (dem.nx - 1);
      const y1 = dem.y0 + dem.cs * (dem.ny - 1);
      setRes(
        await runField3D(
          {
            dem_id: dem.dem_id, Lw: lw, G, atm, mode, source: src, hr,
            grid: { x0: dem.x0, x1, nx: gridN.nx, y0: dem.y0, y1, ny: gridN.ny },
            obstacles: obstacles.map(toObstacle),
            limits: hasLimits ? limits : undefined,
            enclosure,
            ...groundExtras(),
          },
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

  const zmat = useMemo(() => {
    if (!res) return null;
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
      return (k === "Lp" ? res.Lp : k === "LpA" ? res.LpA : res.Abar)[i][band];
    };
    const m: (number | null)[][] = [];
    for (let j = 0; j < res.NY; j++) {
      const row: (number | null)[] = [];
      for (let i = 0; i < res.NX; i++) row.push(pick(j * res.NX + i));
      m.push(row);
    }
    return m;
  }, [res, metric]);

  // Path geometry for the selected receiver (direct, top, lateral) from the same MATLAB code
  useEffect(() => {
    if (!dem || !res || sel == null || !res.valid[sel]) {
      setPathInfo(null);
      return;
    }
    let alive = true;
    setPathBusy(true);
    runCase3D({
      dem_id: dem.dem_id, Lw: lw, G, atm, mode, source: src,
      receiver: { x: res.x[sel % res.NX], y: res.y[Math.floor(sel / res.NX)], h: hr },
      obstacles: obstacles.map(toObstacle), limits: hasLimits ? limits : undefined, enclosure, ...groundExtras(),
    })
      .then((r) => alive && setPathInfo(r))
      .catch(() => alive && setPathInfo(null))
      .finally(() => alive && setPathBusy(false));
    return () => {
      alive = false;
    };
  }, [sel, res]); // eslint-disable-line react-hooks/exhaustive-deps

  function addWall() {
    if (!dem) return;
    const cx = dem.x0 + (dem.cs * (dem.nx - 1)) / 2;
    setObstacles([...obstacles, { kind: "wall", x1: cx, y1: src.y - 20, x2: cx, y2: src.y + 20, h: 5, gap: 0, fab: newFab() }]);
  }
  function addBuilding() {
    if (!dem) return;
    const cx = dem.x0 + (dem.cs * (dem.nx - 1)) / 2;
    setObstacles([...obstacles, { kind: "building", x0: cx - 20, x1: cx + 20, y0: src.y - 10, y1: src.y + 10, h: 8, gap: 0, fab: newFab() }]);
  }
  const setObs = (i: number, patch: Partial<Record<string, number>>) =>
    setObstacles(obstacles.map((o, j) => (j === i ? ({ ...o, ...patch } as ObsRow) : o)));
  const setFab = (i: number, patch: Partial<Fab>) => setObstacles(obstacles.map((o, j) => (j === i ? { ...o, fab: { ...o.fab, ...patch } } : o)));

  function onPick(x: number, y: number) {
    if (clickMode === "source") {
      setSrc({ ...src, x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 });
      return;
    }
    if (!res) return;
    setSel(nearest(res.y, y) * res.NX + nearest(res.x, x));
  }

  // 2D map
  useEffect(() => {
    const el = mapRef.current;
    if (tab !== "map" || !el || !dem) return;
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim() || "#222";
    const line = css.getPropertyValue("--line").trim() || "#ddd";
    const isC = metric === "compliance";
    const data: Plotly.Data[] = [];
    if (res && zmat) {
      data.push(
        isC
          ? ({ type: "heatmap", x: res.x, y: res.y, z: zmat, zmin: 0, zmax: 1, showscale: false, hoverongaps: false,
              colorscale: [[0, "#b03030"], [0.5, "#b03030"], [0.5, "#2e8b57"], [1, "#2e8b57"]],
              hovertemplate: "x %{x:.0f} m, y %{y:.0f} m<extra></extra>" } as Plotly.Data)
          : ({ type: "contour", x: res.x, y: res.y, z: zmat, connectgaps: false, hoverongaps: false,
              contours: { coloring: "heatmap", showlabels: true, labelfont: { size: 10, color: "#fff" } },
              line: { width: 0.6, color: "rgba(255,255,255,0.6)" }, colorscale: "Viridis", reversescale: true,
              colorbar: { title: { text: metric === "bbA" ? "L_p,A dB(A)" : "dB" }, thickness: 12, len: 0.9 },
              hovertemplate: "x %{x:.0f} m, y %{y:.0f} m<br>%{z:.1f}<extra></extra>" } as Plotly.Data),
      );
    }
    if (surf) {
      const xs = Array.from({ length: surf.nx }, (_, i) => surf.x0 + i * surf.cs);
      const ys = Array.from({ length: surf.ny }, (_, i) => surf.y0 + i * surf.cs);
      data.push({
        type: "contour", x: xs, y: ys, z: surf.Z, showscale: false, hoverinfo: "skip",
        contours: { coloring: "none", showlabels: false }, line: { color: ink, width: 0.6 }, opacity: 0.45,
        ncontours: 12, name: "Terrain contours",
      } as Plotly.Data);
    }
    areas.forEach((a) => {
      const q = parsePts(a.pts);
      if (q.x.length >= 3) data.push({ type: "scatter", mode: "lines", x: [...q.x, q.x[0]], y: [...q.y, q.y[0]], line: { color: "rgba(46,139,87,0.95)", dash: "dash", width: 1.5 }, name: `ground G = ${a.G}`, hoverinfo: "name" } as Plotly.Data);
    });
    obstacles.forEach((o, i) => {
      const o2 = toObstacle(o);
      const xs = o.kind !== "wall" ? [...o2.x, o2.x[0]] : o2.x;
      const ys = o.kind !== "wall" ? [...o2.y, o2.y[0]] : o2.y;
      data.push({
        type: "scatter", mode: "lines", x: xs, y: ys, name: `${o.kind} ${i + 1} (${o.h} m)`, hoverinfo: "name",
        line: { color: "#c0392b", width: o.kind === "wall" ? 4 : 2 }, fill: o.kind !== "wall" ? "toself" : "none", fillcolor: "rgba(192,57,43,0.25)",
      } as Plotly.Data);
    });
    if (pathInfo?.valid && pathInfo.paths) {
      const line = (rows: number[][], color: string, dash: string, name: string) =>
        rows.length > 1 &&
        data.push({ type: "scatter", mode: "lines+markers", x: rows.map((p) => p[0]), y: rows.map((p) => p[1]), name, hoverinfo: "name",
          line: { color, dash, width: 2 }, marker: { size: 5, color } } as Plotly.Data);
      line(asRows(pathInfo.paths.direct), "#7f8c8d", "dot", "Direct line");
      line(asRows(pathInfo.paths.left), "#e67e22", "solid", "Lateral path (left)");
      line(asRows(pathInfo.paths.right), "#16a085", "solid", "Lateral path (right)");
    }
    data.push({ type: "scatter", mode: "markers", x: [src.x], y: [src.y], marker: { symbol: "diamond", size: 11, color: ink, line: { color: "#fff", width: 1 } }, name: "Source", hoverinfo: "name" });
    if (res && sel != null && res.valid[sel]) {
      data.push({ type: "scatter", mode: "markers", x: [res.x[sel % res.NX]], y: [res.y[Math.floor(sel / res.NX)]], marker: { symbol: "circle-open", size: 12, color: ink, line: { width: 2 } }, name: "Selected", hoverinfo: "name" });
    }
    const x1 = dem.x0 + dem.cs * (dem.nx - 1);
    const y1 = dem.y0 + dem.cs * (dem.ny - 1);
    Plotly.react(el, data, {
      margin: { l: 56, r: 12, t: 8, b: 44 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "Inter, Segoe UI, sans-serif", size: 12, color: ink }, showlegend: false,
      xaxis: { title: { text: "Easting x, m (projected CRS)" }, range: [dem.x0, x1], gridcolor: line, constrain: "domain" },
      yaxis: { title: { text: "Northing y, m" }, range: [dem.y0, y1], gridcolor: line, scaleanchor: "x", scaleratio: 1 },
    }, { displayModeBar: false, responsive: true });
    const any = el as unknown as { removeAllListeners?: (n: string) => void; on: (n: string, f: (e: Plotly.PlotMouseEvent) => void) => void };
    any.removeAllListeners?.("plotly_click");
    any.on("plotly_click", (ev) => {
      const p = ev.points[0];
      if (p && p.x != null && p.y != null) onPick(Number(p.x), Number(p.y));
    });
  }, [tab, res, zmat, surf, src, sel, metric, clickMode, dem, obstacles, areas, pathInfo]); // eslint-disable-line react-hooks/exhaustive-deps

  // 3D surface draped with the prediction
  useEffect(() => {
    const el = d3Ref.current;
    if (tab !== "3d" || !el || !res || !zmat) return;
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim() || "#222";
    const ground: (number | null)[][] = [];
    for (let j = 0; j < res.NY; j++) ground.push(res.ground.slice(j * res.NX, (j + 1) * res.NX));
    const isC = metric === "compliance";
    const flat = zmat.flat().filter((v): v is number => v != null);
    const sz = (res.x[res.NX - 1] - res.x[0]) || 1;
    const zs = ground.flat().filter((v): v is number => v != null);
    const srcZ = (() => {
      const ix = nearest(res.x, src.x), iy = nearest(res.y, src.y);
      return (ground[iy]?.[ix] ?? 0) + src.h;
    })();
    Plotly.react(el, [
      {
        type: "surface", x: res.x, y: res.y, z: ground, surfacecolor: zmat,
        cmin: isC ? 0 : Math.min(...flat), cmax: isC ? 1 : Math.max(...flat),
        colorscale: isC ? [[0, "#b03030"], [0.5, "#b03030"], [0.5, "#2e8b57"], [1, "#2e8b57"]] : "Viridis", reversescale: !isC,
        showscale: !isC, colorbar: { title: { text: metric === "bbA" ? "dB(A)" : "dB" }, thickness: 12, len: 0.7 },
        hovertemplate: "x %{x:.0f} m<br>y %{y:.0f} m<br>ground %{z:.1f} m<extra></extra>", lighting: { ambient: 0.8, diffuse: 0.5 },
      } as Plotly.Data,
      { type: "scatter3d", mode: "markers", x: [src.x], y: [src.y], z: [srcZ], marker: { size: 5, color: ink, symbol: "diamond" }, name: "Source", hoverinfo: "name" } as Plotly.Data,
      ...obstacles.map((o, i) => {
        const o2 = toObstacle(o);
        const xs = o.kind !== "wall" ? [...o2.x, o2.x[0]] : o2.x;
        const ys = o.kind !== "wall" ? [...o2.y, o2.y[0]] : o2.y;
        const base = Math.max(...zs, 0);
        return { type: "scatter3d", mode: "lines", x: xs, y: ys, z: xs.map(() => base + o.h), line: { color: "#c0392b", width: 6 }, name: `${o.kind} ${i + 1}`, hoverinfo: "name" } as Plotly.Data;
      }),
      ...(pathInfo?.valid && pathInfo.paths
        ? ([["direct", "#7f8c8d"], ["top", ink], ["left", "#e67e22"], ["right", "#16a085"]] as const).flatMap(([k, col]) => {
            const rows = asRows((pathInfo.paths as Record<string, number[][] | number[]>)[k]);
            return rows.length > 1
              ? [{ type: "scatter3d", mode: "lines+markers", x: rows.map((p) => p[0]), y: rows.map((p) => p[1]), z: rows.map((p) => p[2]), line: { color: col, width: k === "top" ? 5 : 3 }, marker: { size: 3, color: col }, name: k, hoverinfo: "name" } as Plotly.Data]
              : [];
          })
        : []),
    ], {
      margin: { l: 0, r: 0, t: 0, b: 0 }, paper_bgcolor: "rgba(0,0,0,0)", font: { color: ink, size: 11 }, showlegend: false,
      scene: {
        aspectmode: "manual", aspectratio: { x: 1, y: (res.y[res.NY - 1] - res.y[0]) / sz || 1, z: Math.min(0.5, Math.max(0.12, (Math.max(...zs) - Math.min(...zs)) / sz * 2.5)) },
        xaxis: { title: { text: "x, m" } }, yaxis: { title: { text: "y, m" } }, zaxis: { title: { text: "ground z, m" } },
      },
    }, { displayModeBar: false, responsive: true });
    const any = el as unknown as { removeAllListeners?: (n: string) => void; on: (n: string, f: (e: Plotly.PlotMouseEvent) => void) => void };
    any.removeAllListeners?.("plotly_click");
    any.on("plotly_click", (ev) => {
      const p = ev.points[0];
      if (p && p.x != null && p.y != null) onPick(Number(p.x), Number(p.y));
    });
  }, [tab, res, zmat, src, metric, clickMode, obstacles, pathInfo]); // eslint-disable-line react-hooks/exhaustive-deps

  const selData: PointData | null = useMemo(() => {
    if (!res || sel == null) return null;
    const c = res.compliance;
    return {
      valid: res.valid[sel], Lp: res.Lp[sel], LpA: res.LpA[sel], Abar: res.Abar[sel], Agr: res.Agr[sel],
      bb: res.Lp_broadband[sel], bbA: res.LpA_broadband[sel], kind: res.kind[sel],
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
  const selTitle = res && sel != null ? `Receiver x = ${res.x[sel % res.NX].toFixed(1)} m, y = ${res.y[Math.floor(sel / res.NX)].toFixed(1)} m, ground ${res.ground[sel] == null ? "n/a" : res.ground[sel]!.toFixed(1) + " m"}, height above ground ${hr} m` : "";

  return (
    <div>
      <div className="scene">
        <div>
          <h2>Terrain (DEM)</h2>
          <div className="tabs">
            {(["hill", "ridge", "flat"] as const).map((k) => (
              <button key={k} onClick={() => load(() => syntheticDem(k))}>Synthetic {k}</button>
            ))}
          </div>
          <p className="note">Synthetic terrain is for demonstration only, not survey data.</p>
          <label className="field"><span>Import file</span>
            <input type="file" accept=".asc,.txt,.csv,.xyz,.tif,.tiff" onChange={(e) => { const f = e.target.files?.[0]; if (f) load(() => uploadDem(f, unit, metricDecl)); }} />
          </label>
          <label className="field"><span>Vertical unit</span>
            <select value={unit} onChange={(e) => setUnit(e.target.value)}><option value="m">metres</option><option value="ft">feet</option><option value="us-ft">US survey feet</option></select>
          </label>
          <label className="field"><span>Horizontal units are metres (needed for files without a CRS)</span>
            <input type="checkbox" checked={metricDecl} onChange={(e) => setMetricDecl(e.target.checked)} />
          </label>
          {dem && (
            <p className="note">
              {dem.meta.source}: {dem.nx} x {dem.ny} cells, {dem.cs} m cells, CRS {dem.crs}, elevation {dem.zmin.toFixed(1)} to {dem.zmax.toFixed(1)} m
              {dem.nan_cells > 0 && `, ${dem.nan_cells} no-data cells`}. {dem.meta.notes?.join(" ")}
            </p>
          )}
        </div>
        <div>
          <h2>Source and receivers</h2>
          {(["x", "y", "h"] as const).map((k) => (
            <label key={k} className="field"><span>Source {k === "h" ? "height above ground" : k}</span>
              <span className="inputwrap"><input type="number" value={src[k]} onChange={(e) => setSrc({ ...src, [k]: parseFloat(e.target.value) })} /><em>m</em></span>
            </label>
          ))}
          <label className="field"><span>Receiver height above ground</span>
            <span className="inputwrap"><input type="number" step={0.1} value={hr} onChange={(e) => setHr(parseFloat(e.target.value))} /><em>m</em></span>
          </label>
          <label className="field"><span>Grid columns</span><span className="inputwrap"><input type="number" value={gridN.nx} onChange={(e) => setGridN({ ...gridN, nx: parseInt(e.target.value, 10) })} /><em></em></span></label>
          <label className="field"><span>Grid rows</span><span className="inputwrap"><input type="number" value={gridN.ny} onChange={(e) => setGridN({ ...gridN, ny: parseInt(e.target.value, 10) })} /><em></em></span></label>
          <h2>Named receivers (for saved cases)</h2>
          {rcv.map((q, i) => (
            <div key={i} className="trow">
              <input style={{ width: 70 }} value={q.name} onChange={(e) => setRcv(rcv.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))} aria-label="Receiver name" />
              <input type="number" title="x, m" value={q.x} onChange={(e) => setRcv(rcv.map((r, j) => (j === i ? { ...r, x: parseFloat(e.target.value) } : r)))} />
              <input type="number" title="y, m" value={q.y} onChange={(e) => setRcv(rcv.map((r, j) => (j === i ? { ...r, y: parseFloat(e.target.value) } : r)))} />
              <input type="number" title="height above ground, m" step={0.1} value={q.h} onChange={(e) => setRcv(rcv.map((r, j) => (j === i ? { ...r, h: parseFloat(e.target.value) } : r)))} />
              <button disabled={rcv.length <= 1} onClick={() => setRcv(rcv.filter((_, j) => j !== i))}>x</button>
            </div>
          ))}
          <button onClick={() => setRcv([...rcv, { name: `R${rcv.length + 1}`, x: 150, y: 150, h: 1.5 }])}>Add receiver</button>
          <p className="note">Each row: name, x, y (m), height above ground (m).</p>
          <p className="note">The grid covers the whole DEM; receivers follow the terrain. About {(gridN.nx * gridN.ny * 0.012).toFixed(0)} s expected. VERIFIED geometry only; no FAST mode.</p>
        </div>
        <LimitsEditor value={lim} onChange={setLim} />
      </div>

      <h2>Obstacles (walls and buildings)</h2>
      <div className="tabs">
        <button disabled={!dem} onClick={addWall}>Add wall</button>
        <button disabled={!dem} onClick={addBuilding}>Add building</button>
        <span className="note">Heights are above the highest ground under the obstacle. A wall is a thin centre line (one diffracting edge); a building adds multiple edges.</span>
      </div>
      {obstacles.map((o, i) => (
        <div key={i} className="orow">
          <strong>{o.kind === "wall" ? "Wall" : o.kind === "building" ? "Building" : "Polygon"} {i + 1}</strong>
          {o.kind === "polygon" && (
            <label className="band" style={{ width: 150 }}><span>vertices, one "x y" per line</span>
              <textarea rows={4} value={o.pts} onChange={(e) => setObstacles(obstacles.map((q, j) => (j === i && q.kind === "polygon" ? { ...q, pts: e.target.value } : q)))} />
            </label>
          )}
          {o.kind !== "polygon" && (o.kind === "wall" ? (["x1", "y1", "x2", "y2"] as const) : (["x0", "x1", "y0", "y1"] as const)).map((k) => (
            <label key={k} className="band"><span>{k}</span>
              <input type="number" value={(o as unknown as Record<string, number>)[k]} onChange={(e) => setObs(i, { [k]: parseFloat(e.target.value) })} />
            </label>
          ))}
          <label className="band"><span>height m</span><input type="number" step={0.5} value={o.h} onChange={(e) => setObs(i, { h: parseFloat(e.target.value) })} /></label>
          <label className="band"><span>bottom gap m</span><input type="number" step={0.1} value={o.gap} onChange={(e) => setObs(i, { gap: parseFloat(e.target.value) })} /></label>
          <label className="band"><span>fabric</span><input type="checkbox" checked={o.fab.on} onChange={(e) => setFab(i, { on: e.target.checked })} /></label>
          {o.fab.on && (
            <>
              <select value={o.fab.mode} onChange={(e) => setFab(i, { mode: e.target.value as "mass" | "tl" })}>
                <option value="mass">surface mass (rough)</option>
                <option value="tl">measured TL(f)</option>
              </select>
              {o.fab.mode === "mass" ? (
                <label className="band"><span>kg/m2</span><input type="number" step={0.1} value={o.fab.mass} onChange={(e) => setFab(i, { mass: parseFloat(e.target.value) })} /></label>
              ) : (
                BANDS.map((f, k) => (
                  <label key={f} className="band" style={{ width: 52 }}><span>{f}</span>
                    <input type="number" value={o.fab.tl[k]} onChange={(e) => setFab(i, { tl: o.fab.tl.map((v, j) => (j === k ? e.target.value : v)) })} />
                  </label>
                ))
              )}
              <label className="band"><span>open 0..1</span><input type="number" step={0.05} value={o.fab.open} onChange={(e) => setFab(i, { open: parseFloat(e.target.value) })} /></label>
            </>
          )}
          <button title="Delete obstacle" onClick={() => setObstacles(obstacles.filter((_, j) => j !== i))}>x</button>
        </div>
      ))}

      <h2>Ground</h2>
      <p className="note">The left-panel G applies everywhere. Draw areas with their own ground factor G (areas must not overlap); each region of the source-receiver path then takes the length-weighted mean (ISO 9613-2 Formula 10).</p>
      {areas.map((a, i) => (
        <div key={i} className="orow">
          <strong>Area {i + 1}</strong>
          <label className="band" style={{ width: 150 }}><span>vertices, one "x y" per line</span>
            <textarea rows={4} value={a.pts} onChange={(e) => setAreas(areas.map((q, j) => (j === i ? { ...q, pts: e.target.value } : q)))} />
          </label>
          <label className="band"><span>G 0..1</span><input type="number" step={0.05} value={a.G} onChange={(e) => setAreas(areas.map((q, j) => (j === i ? { ...q, G: parseFloat(e.target.value) } : q)))} /></label>
          <button title="Delete area" onClick={() => setAreas(areas.filter((_, j) => j !== i))}>x</button>
        </div>
      ))}
      <div className="tabs">
        <button disabled={!dem} onClick={() => dem && setAreas([...areas, { pts: `${dem.x0} ${dem.y0}\n${dem.x0 + dem.cs * (dem.nx - 1)} ${dem.y0}\n${dem.x0 + dem.cs * (dem.nx - 1)} ${dem.y0 + dem.cs * (dem.ny - 1)}\n${dem.x0} ${dem.y0 + dem.cs * (dem.ny - 1)}`, G: 0.5 }])}>Add ground area</button>
        <label className="field"><span>G outside the areas (empty = left-panel G)</span><input type="number" step={0.05} value={gDefault} onChange={(e) => setGDefault(e.target.value)} /></label>
        <label className="field"><span>Ground method</span>
          <select value={gMethod} onChange={(e) => setGMethod(e.target.value as "general" | "simplified")}>
            <option value="general">general (octave bands, ISO 9613-2 7.3.1)</option>
            <option value="simplified">simplified, A-weighted only (7.3.2)</option>
          </select>
        </label>
      </div>

      <div className="tabs">
        <button className="primary" disabled={!ready || busy || !dem} onClick={() => run(true)}>{busy ? "Running" : "Run 3D map"}</button>
        {dem && (
          <SaveCase
            kind="terrain"
            project={project ?? null}
            defaultName="Terrain case"
            editing={initial && dem.dem_id.startsWith("asset:") ? { id: initial.id, name: initial.name } : null}
            buildEdit={() => ({
              request: {
                Lw: lw, G, atm, mode, source: src, hr,
                grid: { x0: dem.x0, x1: dem.x0 + dem.cs * (dem.nx - 1), nx: gridN.nx, y0: dem.y0, y1: dem.y0 + dem.cs * (dem.ny - 1), ny: gridN.ny },
                obstacles: obstacles.map(toObstacle), limits: hasLimits ? limits : undefined, enclosure, ...groundExtras(),
              },
              dem_asset: initial?.input?.dem_asset, dem_info: initial?.input?.dem_info,
              receivers: rcv, run_field: true,
            })}
            build={() => ({
              request: {
                dem_id: dem.dem_id, Lw: lw, G, atm, mode, source: src, hr,
                grid: { x0: dem.x0, x1: dem.x0 + dem.cs * (dem.nx - 1), nx: gridN.nx, y0: dem.y0, y1: dem.y0 + dem.cs * (dem.ny - 1), ny: gridN.ny },
                obstacles: obstacles.map(toObstacle), limits: hasLimits ? limits : undefined, enclosure, ...groundExtras(),
              },
              receivers: rcv, run_field: true,
            })}
          />
        )}
        <button className={tab === "map" ? "on" : ""} onClick={() => setTab("map")}>Map</button>
        <button className={tab === "3d" ? "on" : ""} onClick={() => setTab("3d")}>3D surface</button>
        <select value={metric} onChange={(e) => setMetric(e.target.value)}>
          {metricOptions.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={clickMode} onChange={(e) => setClickMode(e.target.value as "inspect" | "source")}>
          <option value="inspect">Click: inspect receiver</option>
          <option value="source">Click: place source</option>
        </select>
        {res && <span className="muted">{res._meta.cache_hit ? "cached" : `${res._meta.seconds.toFixed(1)} s`}</span>}
        {res && <button onClick={() => { const el = tab === "map" ? mapRef.current : d3Ref.current; if (el) void Plotly.downloadImage(el, { format: "png", width: 1800, height: 1200, scale: 2, filename: tab === "map" ? "noise-map" : "noise-3d" }); }}>Download PNG</button>}
      </div>
      {err && <div className="error">{err}</div>}
      {!dem && <p className="muted">Load a synthetic terrain or import a DEM to begin.</p>}
      {tab === "map" && <div ref={mapRef} style={{ width: "100%", height: 460 }} />}
      {tab === "3d" && (res ? <div ref={d3Ref} style={{ width: "100%", height: 460 }} /> : <p className="muted">Run the 3D map first.</p>)}
      {res && <p className="note">{res.method}. Lateral paths exist only around the vertical edges of the obstacles you define; a raster alone does not define lateral edges, so hills get none.</p>}
      {selData && <PointInspector title={selTitle} data={selData} limits={limits.bands} weighting={limits.weighting} hasLimits={hasLimits} />}
      {selData && pathInfo?.valid && pathInfo.geom && pathInfo.out && (
        <div className="inspector">
          <h2>Propagation paths {pathBusy ? "(updating)" : ""}</h2>
          <table>
            <thead><tr><th>Path</th><th>Status</th><th>z, m</th><th>d_ss, m</th><th>d_sr, m</th><th>e, m</th></tr></thead>
            <tbody>
              <tr>
                <td>Top (vertical plane)</td>
                <td>{pathInfo.geom.kind === "blocked" ? "blocked: taut-string path" : pathInfo.geom.kind === "clear_crest" ? "clear LOS, negative z over a crest" : "no relevant edge"}</td>
                <td>{f2(asArr(pathInfo.geom.z)[0], 3)}</td><td>{f2(asArr(pathInfo.geom.dss)[0])}</td><td>{f2(asArr(pathInfo.geom.dsr)[0])}</td><td>{f2(pathInfo.geom.e)}</td>
              </tr>
              {(["left", "right"] as const).map((s) => {
                const p = pathInfo.geom!.lateral[s];
                return (
                  <tr key={s}>
                    <td>Lateral, {s}</td>
                    <td>{p.valid ? "used" : (pathInfo.geom!.lateral.reason || p.reason || "not available")}</td>
                    <td>{f2(p.z, 3)}</td><td>{f2(p.dss)}</td><td>{f2(p.dsr)}</td><td>{f2(p.e)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <table>
            <thead><tr><th>Hz</th><th>A_gr</th><th>A_bar top</th><th>A_bar left</th><th>A_bar right</th><th>A_bar combined</th></tr></thead>
            <tbody>
              {BANDS.map((f, i) => (
                <tr key={f}>
                  <td>{f}</td><td>{f2(pathInfo.out!.Agr[i])}</td><td>{f2(pathInfo.out!.Abar_top[i])}</td>
                  <td>{f2(pathInfo.out!.Abar_side1[i])}</td><td>{f2(pathInfo.out!.Abar_side2[i])}</td><td>{f2(pathInfo.out!.Abar[i])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pathInfo.geom.under?.present && <p className="note">Path under the bottom gap included (z = {f2(pathInfo.geom.under.z, 3)} m). Engineering extension: not prescribed by ISO 9613-2.</p>}
          {pathInfo.out.screen && (
            <>
              <h2>Transmissive screen (engineering approximation, not ISO 9613-2)</h2>
              <table>
                <thead><tr><th>Hz</th><th>A_bar opaque</th><th>TL</th><th>A_eff</th><th>L diffracted</th><th>L transmitted</th></tr></thead>
                <tbody>
                  {BANDS.map((f, i) => (
                    <tr key={f}>
                      <td>{f}</td><td>{f2(pathInfo.out!.screen!.Abar_opaque[i])}</td><td>{f2(pathInfo.out!.screen!.TL[i])}</td>
                      <td>{f2(pathInfo.out!.screen!.A_eff[i])}</td><td>{f2(pathInfo.out!.screen!.L_diffracted[i], 1)}</td><td>{f2(pathInfo.out!.screen!.L_transmitted[i], 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className={pathInfo.out.screen.opaqueAssumptionOK ? "note" : "badc"}>
                {pathInfo.out.screen.opaqueAssumptionOK
                  ? "Rule of thumb met: TL exceeds A_bar by at least 10 dB in every screened band (a rule of thumb, not an ISO requirement)."
                  : "Transmission is NOT substantially weaker than diffraction: treating this screen as opaque would overstate its effect."}
              </p>
              <ul className="note">
                {([] as string[]).concat(pathInfo.out.screen.info?.materials ?? []).map((m) => <li key={m}>{m}</li>)}
                {([] as string[]).concat(pathInfo.out.screen.info?.warnings ?? []).map((m) => <li key={m}>{m}</li>)}
              </ul>
              <p className="note">{pathInfo.out.screen.method}. This result is approximate; it is not a compliance statement.</p>
            </>
          )}
          <p className="note">Combined by ISO 9613-2:2024 Formula (25); a path that is not relevant contributes 0 to the sum. Lateral paths are ignored when terrain contributes to the top path and by the factor-8 rule (7.4.3). Map colours: dotted grey direct line, orange/teal lateral paths.</p>
        </div>
      )}
      {selData && pathInfo && !pathInfo.valid && <p className="muted">No path geometry: {pathInfo.reason}</p>}
    </div>
  );
}
