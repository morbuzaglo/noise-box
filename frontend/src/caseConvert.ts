// Conversions from a STORED case request back into the state the editors use, so that opening a case
// is the same as having just defined it. Anything a case can carry must come back, otherwise a reopened
// case would silently run a different scene.
import { EnclosureIn, Limits } from "./api";
import { EncState, defaultEnc } from "./EnclosureEditor";
import { LimitState, defaultLimits } from "./LimitsEditor";

export function encFromRequest(e?: EnclosureIn | null): EncState {
  const d = defaultEnc();
  if (!e) return d;
  const m = e.material ?? {};
  return {
    on: true, S: e.S_total, A: e.A_in, open: e.S_open ?? 0,
    mode: m.TL ? "tl" : "mass", mass: m.surface_mass ?? d.mass, tl: m.TL ? m.TL.map(String) : d.tl,
  };
}

export function limFromRequest(l?: Limits | null): LimitState {
  if (!l) return { bands: ["", "", "", "", "", "", "", ""], weighting: "Z", overallA: "" };
  return {
    bands: (l.bands ?? Array(8).fill(null)).map((v) => (v == null ? "" : String(v))),
    weighting: l.weighting ?? "Z",
    overallA: l.overallA == null ? "" : String(l.overallA),
  };
}

export { defaultLimits };
