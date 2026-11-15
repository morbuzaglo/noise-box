export type Mode = "iso2024" | "draft2026" | "iso1996";

export interface MaterialIn {
  surface_mass?: number;
  TL?: number[];
  openness?: number;
  tl_model?: "normal" | "field";
}

export interface EnclosureIn {
  S_total: number;
  A_in: number;
  S_open: number;
  material: MaterialIn;
}

export interface CaseInput {
  Lw: number[];
  hs: number;
  hr: number;
  dp: number;
  G: { Gs: number; Gm: number; Gr: number };
  atm: { T_C: number; RH: number; p_kPa: number };
  mode: Mode;
  barrier?: { z: number; dss: number; dsr: number; e: number };
  C0?: number;
  enclosure?: EnclosureIn;
}

export interface CaseResult {
  mode: Mode;
  f: number[];
  d: number;
  dp: number;
  Adiv: number[];
  Aatm: number[];
  Agr: number[];
  Abar: number[];
  Amisc: number[];
  Atotal: number[];
  Lw: number[];
  Lp: number[];
  LpA_bands: number[];
  Lp_broadband: number;
  LpA_broadband: number;
  Cmet: number;
  notImplemented: string[];
  enclosure?: { Lw_in: number[]; Lw_out: number[]; reduction: number[]; TLeff: number[]; warnings: string[]; notApplicableBands: boolean[]; model: string };
  _meta: { cache_hit: boolean; reloaded: boolean; seconds: number; cache_key: string };
}

export interface Health {
  matlab: string;
  library: string;
  stats: { runs: number; cache_hits: number; reloads: number };
}

export const BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000];
// A-weighting corrections per octave band, dB. PROVISIONAL values from the
// project brief (IEC 61672-1 rounded); keep identical to matlab/core/nb_bands.m.
export const A_WEIGHT = [-26.2, -16.1, -8.6, -3.2, 0, 1.2, 1.0, -1.1];

export interface Limits {
  bands: (number | null)[];
  weighting: "Z" | "A";
  overallA: number | null;
}

export interface Field2DRequest {
  Lw: number[];
  G: { Gs: number; Gm: number; Gr: number };
  atm: { T_C: number; RH: number; p_kPa: number };
  mode: Mode;
  terrain: { x: number[]; z: number[] };
  source_x: number;
  source_h: number;
  grid: { x0: number; x1: number; nx: number; z0: number; z1: number; nz: number };
  limits?: Limits;
  enclosure?: EnclosureIn;
}

export interface Field2DResult {
  x: number[];
  z: number[];
  NX: number;
  NZ: number;
  Lp: (number | null)[][];
  LpA: (number | null)[][];
  Abar: (number | null)[][];
  Agr: (number | null)[][];
  Lp_broadband: (number | null)[];
  LpA_broadband: (number | null)[];
  kind: (number | null)[];
  valid: boolean[];
  compliance?: {
    code: (number | null)[];
    margin: (number | null)[][];
    exceed: boolean[][];
    worstBand: number[];
    worstMargin: (number | null)[];
    overallMargin: (number | null)[];
    overallExceed: boolean[];
  };
  _meta: { cache_hit: boolean; reloaded: boolean; seconds: number };
}

export async function runField2D(req: Field2DRequest, useCache = true): Promise<Field2DResult> {
  const r = await fetch(`/api/field2d?use_cache=${useCache}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export interface DemInfo {
  dem_id: string;
  x0: number;
  y0: number;
  cs: number;
  nx: number;
  ny: number;
  crs: string;
  zmin: number;
  zmax: number;
  nan_cells: number;
  meta: { source: string; format: string; notes?: string[] };
}

export interface DemSurface {
  x0: number;
  y0: number;
  cs: number;
  nx: number;
  ny: number;
  Z: (number | null)[][];
  stride: number;
}

export interface Field3DRequest {
  dem_id: string;
  Lw: number[];
  G: { Gs: number; Gm: number; Gr: number };
  atm: { T_C: number; RH: number; p_kPa: number };
  mode: Mode;
  source: { x: number; y: number; h: number };
  grid: { x0: number; x1: number; nx: number; y0: number; y1: number; ny: number };
  hr: number;
  obstacles?: ObstacleIn[];
  limits?: Limits;
  enclosure?: EnclosureIn;
  ground_areas?: GroundAreaIn[];
  ground_default?: number | null;
  ground_method?: "general" | "simplified";
}

export interface GroundAreaIn {
  x: number[];
  y: number[];
  G: number;
}

export interface Field3DResult {
  x: number[];
  y: number[];
  NX: number;
  NY: number;
  Lp: (number | null)[][];
  LpA: (number | null)[][];
  Abar: (number | null)[][];
  Agr: (number | null)[][];
  Lp_broadband: (number | null)[];
  LpA_broadband: (number | null)[];
  kind: (number | null)[];
  valid: boolean[];
  ground: (number | null)[];
  method: string;
  compliance?: Field2DResult["compliance"];
  _meta: { cache_hit: boolean; reloaded: boolean; seconds: number };
}

export interface ObstacleIn {
  kind: "wall" | "building";
  x: number[];
  y: number[];
  h: number;
  name?: string;
  gap?: number;
  material?: MaterialIn;
}

export interface LateralSide {
  valid: boolean;
  reason?: string;
  z?: number;
  dss?: number;
  dsr?: number;
  e?: number;
  maxv?: number;
}

export interface Case3DResult {
  valid: boolean;
  reason: string;
  out?: {
    d: number;
    Abar: number[];
    Abar_top: number[];
    Abar_side1: number[];
    Abar_side2: number[];
    Agr: number[];
    Lp: number[];
    LpA_bands: number[];
    screenApplied?: boolean;
    screen?: {
      Abar_opaque: number[];
      TL: number[];
      A_eff: number[];
      L_diffracted: number[];
      L_transmitted: number[];
      opaqueAssumptionOK: boolean;
      method: string;
      info?: { materials: string[] | string; warnings: string[] | string };
    };
    barrierBandApplicable?: boolean[];
  };
  geom?: {
    kind: string;
    z: number | number[];
    dss: number | number[];
    dsr: number | number[];
    e: number;
    blockers: number | number[];
    under?: { present: boolean; z?: number; note?: string };
    lateral: { considered: boolean; reason: string; maxVerticalSupportDistance?: number; left: LateralSide; right: LateralSide };
  };
  paths?: { direct: number[][]; top: number[][]; left: number[][] | number[]; right: number[][] | number[] };
}

export const runCase3D = (req: Record<string, unknown>, useCache = true) =>
  fetch(`/api/case3d?use_cache=${useCache}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }).then((r) =>
    jsonOrThrow<Case3DResult>(r),
  );

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = await r.text();
    try {
      msg = JSON.parse(msg).detail ?? msg;
    } catch {
      /* keep raw text */
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

export const syntheticDem = (kind: "flat" | "ridge" | "hill") =>
  fetch("/api/dem/synthetic", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind }) }).then((r) =>
    jsonOrThrow<DemInfo>(r),
  );

export function uploadDem(file: File, verticalUnit: string, declaredMetric: boolean) {
  const f = new FormData();
  f.append("file", file);
  f.append("vertical_unit", verticalUnit);
  f.append("declared_metric", String(declaredMetric));
  return fetch("/api/dem/upload", { method: "POST", body: f }).then((r) => jsonOrThrow<DemInfo>(r));
}

export const getDemSurface = (id: string, stride: number) => fetch(`/api/dem/${id}?stride=${stride}`).then((r) => jsonOrThrow<DemSurface>(r));

export const runField3D = (req: Field3DRequest, useCache = true) =>
  fetch(`/api/field3d?use_cache=${useCache}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }).then((r) =>
    jsonOrThrow<Field3DResult>(r),
  );

export async function getHealth(): Promise<Health> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}

export async function runCase(c: CaseInput, useCache = true): Promise<CaseResult> {
  const r = await fetch(`/api/run?use_cache=${useCache}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(c),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t);
  }
  return r.json();
}

export interface AudioInfo {
  audio_id: string;
  fs: number;
  channels: number;
  duration: number;
  name: string;
  peak: number;
  format: string;
}

export interface Waveform {
  t: number[];
  min: number[];
  max: number[];
  duration: number;
  fs: number;
}

export interface IntervalIn {
  audio_id: string;
  start: number;
  stop: number;
  channel?: number;
}

export interface AudioAnalysisRequest {
  signal: IntervalIn;
  calibration: {
    mode: "none" | "sensitivity" | "calibrator";
    pa_per_unit?: number;
    calibrator?: IntervalIn & { level: number; freq: number };
  };
  background?: IntervalIn;
  estimate?: {
    hs: number;
    hm: number;
    dp: number;
    dh: number;
    G: { Gs: number; Gm: number; Gr: number };
    atm: { T_C: number; RH: number; p_kPa: number };
    Dc?: number[];
    srcDim?: number;
  };
}

export interface AudioAnalysis {
  absolute: boolean;
  L: (number | null)[];
  Lused: (number | null)[];
  warnings: string[] | string;
  paPerUnit?: number | null;
  signal: { unit: string; duration: number; filter: string; noteBroadband: string; broadband: number | null; fs: number };
  calibration?: { paPerUnit: number; toneToTotal_dB: number; note: string; warnings: string[] | string };
  subtraction?: { Lcorr: (number | null)[]; deltaL: (number | null)[]; status: string[]; correction: (number | null)[]; warnings: string[] | string };
  lw?: { Lw: (number | null)[]; A: number[]; d: number; warnings: string[] | string; model: string };
}

export const uploadAudio = (file: File) => {
  const f = new FormData();
  f.append("file", file);
  return fetch("/api/audio/upload", { method: "POST", body: f }).then((r) => jsonOrThrow<AudioInfo>(r));
};

export const getWaveform = (id: string, channel = 1, points = 1500) =>
  fetch(`/api/audio/${id}/waveform?channel=${channel}&points=${points}`).then((r) => jsonOrThrow<Waveform>(r));

export const analyzeAudio = (req: AudioAnalysisRequest, useCache = true) =>
  fetch(`/api/audio/analyze?use_cache=${useCache}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }).then((r) =>
    jsonOrThrow<AudioAnalysis>(r),
  );

export interface ProjectRow {
  id: string;
  name: string;
  description: string;
  created: number;
  updated: number;
  n_cases?: number;
}

export interface ReceiverResult {
  name: string;
  x: number | null;
  y: number | null;
  h: number | null;
  valid: boolean;
  reason?: string;
  path?: string;
  out?: { Lp: (number | null)[]; LpA_bands: (number | null)[]; Lp_broadband: number | null; LpA_broadband: number | null };
  compliance?: { status: string | null; worstBand?: number; worstMargin?: number | null; margin?: (number | null)[] | null };
}

export interface CaseRow {
  id: string;
  project_id: string;
  name: string;
  kind: "point" | "section" | "terrain";
  status: string;
  executed: number | null;
  created: number;
  warnings: string[];
  fingerprint: { file: string[]; md5: string[] } | null;
  input?: { request: Record<string, unknown>; receivers?: Record<string, unknown>[]; dem_asset?: string; dem_info?: unknown; run_field?: boolean };
  result?: { receivers: ReceiverResult[]; field: { n_points: number; stats: { valid: number; LpA_max: number | null; LpA_min: number | null } } | null; seconds?: number } | null;
}

export interface Comparison {
  cases: { id: string; name: string; status: string; mode: string | null }[];
  table: { receiver: string; cases: Record<string, { LpA: number | null; Lp: number | null; status: string | null } | null> }[];
}

const jsonBody = (b: unknown) => ({ headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });

export const listProjects = () => fetch("/api/projects").then((r) => jsonOrThrow<ProjectRow[]>(r));
export const createProject = (name: string, description = "") =>
  fetch("/api/projects", { method: "POST", ...jsonBody({ name, description }) }).then((r) => jsonOrThrow<ProjectRow>(r));
export const patchProject = (id: string, body: { name?: string; description?: string }) =>
  fetch(`/api/projects/${id}`, { method: "PATCH", ...jsonBody(body) }).then((r) => jsonOrThrow<ProjectRow>(r));
export const duplicateProject = (id: string, name?: string) =>
  fetch(`/api/projects/${id}/duplicate`, { method: "POST", ...jsonBody({ name }) }).then((r) => jsonOrThrow<ProjectRow>(r));
export const deleteProject = (id: string) => fetch(`/api/projects/${id}`, { method: "DELETE" }).then((r) => jsonOrThrow<unknown>(r));
export const getProject = (id: string) => fetch(`/api/projects/${id}`).then((r) => jsonOrThrow<ProjectRow & { cases: CaseRow[] }>(r));
export const createCase = (pid: string, name: string, kind: CaseRow["kind"], input: unknown) =>
  fetch(`/api/projects/${pid}/cases`, { method: "POST", ...jsonBody({ name, kind, input }) }).then((r) => jsonOrThrow<CaseRow>(r));
export const getCase = (id: string) => fetch(`/api/cases/${id}`).then((r) => jsonOrThrow<CaseRow>(r));
export const runStoredCase = (id: string) => fetch(`/api/cases/${id}/run`, { method: "POST" }).then((r) => jsonOrThrow<CaseRow>(r));
export const duplicateCase = (id: string, name: string | undefined, overrides: unknown) =>
  fetch(`/api/cases/${id}/duplicate`, { method: "POST", ...jsonBody({ name, overrides }) }).then((r) => jsonOrThrow<CaseRow>(r));
export const deleteCase = (id: string) => fetch(`/api/cases/${id}`, { method: "DELETE" }).then((r) => jsonOrThrow<unknown>(r));
export const compareCases = (pid: string, ids: string[]) =>
  fetch(`/api/projects/${pid}/compare?case_ids=${ids.join(",")}`).then((r) => jsonOrThrow<Comparison>(r));
export const exportUrl = (pid: string, ids: string[], grid: boolean) => `/api/projects/${pid}/export.xlsx?case_ids=${ids.join(",")}&include_grid=${grid}`;

export interface LabRow {
  id: string;
  group: string;
  title: string;
  source: string;
  calls: string[];
  status0: string;
}

export interface LabResult {
  id: string;
  group: string;
  title: string;
  source: string;
  calls: string[];
  status: string;
  detail: string | null;
  labels: string[];
  expected: (number | null)[];
  actual: (number | null)[];
  err: (number | null)[];
  tol: number[];
  pass: boolean[];
  n: number;
  n_pass: number;
  max_abs_error: number | null;
}

export interface LabSummary {
  results: LabResult[];
  counts: Record<string, number>;
  seconds: number | null;
  meta: { matlab_release: string; software: string } | null;
}

export interface LabScene {
  id: string;
  title: string;
  S: number[];
  R: number[];
  obstacles: { x: number[]; y: number[]; top: number }[];
  areas: { x: number[]; y: number[]; G: number }[];
  mode: string;
}

export const labCatalog = () => fetch("/api/testlab/catalog").then((r) => jsonOrThrow<LabRow[]>(r));
export const labRun = (body: { ids?: string[]; group?: string }) =>
  fetch("/api/testlab/run", { method: "POST", ...jsonBody(body) }).then((r) => jsonOrThrow<LabSummary>(r));
export const labLast = () => fetch("/api/testlab/last").then((r) => jsonOrThrow<LabSummary>(r));
export const labScene = (id: string) => fetch(`/api/testlab/${id}/scene`).then((r) => jsonOrThrow<LabScene>(r));
export const labLoad = (id: string, projectId: string) =>
  fetch(`/api/testlab/${id}/load`, { method: "POST", ...jsonBody({ project_id: projectId }) }).then((r) => jsonOrThrow<CaseRow>(r));

export interface FunctionRow {
  name: string;
  path: string;
  mtime: number;
  signature: string;
  sha256: string;
  dependencies: string[];
  linked_tests: string[];
}

export interface Diagnostics {
  python: string;
  platform: string;
  library: string;
  watching: boolean;
  state: string;
  engine_requirement: string;
  matlab?: { release: string; version: string; toolboxes: string[]; licensed: boolean[]; javaVersion: string };
}

export const getFunctions = () => fetch("/api/functions").then((r) => jsonOrThrow<FunctionRow[]>(r));
export const getDiagnostics = () => fetch("/api/diagnostics").then((r) => jsonOrThrow<Diagnostics>(r));
export const refreshMatlab = () => fetch("/api/matlab/refresh", { method: "POST" }).then((r) => jsonOrThrow<{ reloaded: boolean; stats: Health["stats"] }>(r));
export const setWatch = (on: boolean) => fetch("/api/matlab/watch", { method: "POST", ...jsonBody({ on }) }).then((r) => jsonOrThrow<{ watching: boolean }>(r));

export const restoreCaseDem = (id: string) => fetch(`/api/cases/${id}/dem`).then((r) => jsonOrThrow<DemInfo>(r));
export const updateCase = (id: string, input: unknown) =>
  fetch(`/api/cases/${id}`, { method: "PATCH", ...jsonBody({ input }) }).then((r) => jsonOrThrow<CaseRow>(r));
