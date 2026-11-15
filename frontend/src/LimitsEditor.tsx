import { BANDS, Limits } from "./api";

export interface LimitState {
  bands: string[];
  weighting: "Z" | "A";
  overallA: string;
}

export const defaultLimits = (): LimitState => ({ bands: ["", "", "", "45", "45", "45", "45", "45"], weighting: "Z", overallA: "" });

const num = (s: string) => (s.trim() === "" ? null : parseFloat(s));

export function toLimits(s: LimitState): Limits {
  return { bands: s.bands.map(num), weighting: s.weighting, overallA: num(s.overallA) };
}

export const hasAnyLimit = (l: Limits) => l.bands.some((b) => b != null) || l.overallA != null;

export default function LimitsEditor({ value, onChange }: { value: LimitState; onChange: (v: LimitState) => void }) {
  return (
    <div>
      <h2>Permitted levels</h2>
      <label className="field">
        <span>Limits apply to</span>
        <select value={value.weighting} onChange={(e) => onChange({ ...value, weighting: e.target.value as "Z" | "A" })}>
          <option value="Z">unweighted octave-band L_p</option>
          <option value="A">A-weighted octave-band L_p,A</option>
        </select>
      </label>
      <div className="bands">
        {BANDS.map((f, i) => (
          <label key={f} className="band">
            <span>{f}</span>
            <input
              type="number"
              placeholder="none"
              value={value.bands[i]}
              onChange={(e) => onChange({ ...value, bands: value.bands.map((v, j) => (j === i ? e.target.value : v)) })}
            />
          </label>
        ))}
      </div>
      <label className="field">
        <span>Overall limit</span>
        <span className="inputwrap">
          <input type="number" placeholder="none" value={value.overallA} onChange={(e) => onChange({ ...value, overallA: e.target.value })} />
          <em>dB(A)</em>
        </span>
      </label>
      <p className="note">A point is PASS only if every band that has a limit is at or below it. Empty = no limit for that band.</p>
    </div>
  );
}
