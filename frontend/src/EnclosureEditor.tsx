import { BANDS, EnclosureIn } from "./api";

export interface EncState {
  on: boolean;
  S: number;
  A: number;
  open: number;
  mode: "mass" | "tl";
  mass: number;
  tl: string[];
}

export const defaultEnc = (): EncState => ({ on: false, S: 6, A: 8, open: 0, mode: "tl", mass: 2, tl: ["10", "14", "18", "22", "26", "30", "34", "38"] });

export function toEnclosure(s: EncState): EnclosureIn | undefined {
  if (!s.on) return undefined;
  const tl = s.tl.map((v) => parseFloat(v));
  return {
    S_total: s.S,
    A_in: s.A,
    S_open: s.open,
    material: s.mode === "mass" ? { surface_mass: s.mass } : { TL: tl },
  };
}

// Feature 1: a material enclosure AROUND THE SOURCE. This changes the radiated sound power;
// it is not a diffraction barrier between source and receiver.
export default function EnclosureEditor({ value, onChange }: { value: EncState; onChange: (v: EncState) => void }) {
  const set = (p: Partial<EncState>) => onChange({ ...value, ...p });
  return (
    <div>
      <h2>Source enclosure (optional)</h2>
      <label className="field">
        <span>Enclose the source in a material</span>
        <input type="checkbox" checked={value.on} onChange={(e) => set({ on: e.target.checked })} />
      </label>
      {value.on && (
        <>
          <label className="field"><span>Enclosure surface area</span>
            <span className="inputwrap"><input type="number" value={value.S} onChange={(e) => set({ S: parseFloat(e.target.value) })} /><em>m2</em></span></label>
          <label className="field"><span>Absorption area inside</span>
            <span className="inputwrap"><input type="number" value={value.A} onChange={(e) => set({ A: parseFloat(e.target.value) })} /><em>m2</em></span></label>
          <label className="field"><span>Openings (area)</span>
            <span className="inputwrap"><input type="number" value={value.open} onChange={(e) => set({ open: parseFloat(e.target.value) })} /><em>m2</em></span></label>
          <label className="field"><span>Transmission loss from</span>
            <select value={value.mode} onChange={(e) => set({ mode: e.target.value as "mass" | "tl" })}>
              <option value="tl">measured TL(f), 8 octave bands</option>
              <option value="mass">surface mass (rough mass-law estimate)</option>
            </select>
          </label>
          {value.mode === "mass" ? (
            <label className="field"><span>Surface mass</span>
              <span className="inputwrap"><input type="number" value={value.mass} onChange={(e) => set({ mass: parseFloat(e.target.value) })} /><em>kg/m2</em></span></label>
          ) : (
            <div className="bands">
              {BANDS.map((f, i) => (
                <label key={f} className="band"><span>{f}</span>
                  <input type="number" value={value.tl[i]} onChange={(e) => set({ tl: value.tl.map((v, j) => (j === i ? e.target.value : v)) })} />
                </label>
              ))}
            </div>
          )}
          <p className="note">
            Diffuse interior field assumed: L_W,out = L_W,in + 10 lg(4/A) - TL + 10 lg(S) - 6. Rough engineering estimate; ignores resonance, coincidence,
            near-field and flanking effects. Not a diffraction screen: it changes the source spectrum, not the path.
          </p>
        </>
      )}
    </div>
  );
}
