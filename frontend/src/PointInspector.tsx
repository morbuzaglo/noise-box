import { BANDS } from "./api";
import SpectrumChart from "./SpectrumChart";

export interface PointData {
  valid: boolean;
  Lp: (number | null)[];
  LpA: (number | null)[];
  Abar: (number | null)[];
  Agr: (number | null)[];
  bb: number | null;
  bbA: number | null;
  kind: number | null;
  code: number | null;
  margin: (number | null)[] | null;
  exceed: boolean[] | null;
  worstBand: number;
  worstMargin: number | null;
  overallMargin: number | null;
  overallExceed: boolean;
}

interface Props {
  title: string;
  data: PointData;
  limits: (number | null)[];
  weighting: "Z" | "A";
  hasLimits: boolean;
}

const fmt = (v: number | null | undefined, n = 1) => (v == null || !Number.isFinite(v) ? "no data" : v.toFixed(n));
export const kindName = (k: number | null) =>
  k === 1 ? "line of sight blocked (taut-string path)" : k === 2 ? "clear, real crest below LOS (negative z)" : k === 0 ? "no relevant edge" : "n/a";

export default function PointInspector({ title, data: d, limits, weighting, hasLimits }: Props) {
  const pred = weighting === "A" ? d.LpA : d.Lp;
  return (
    <div className="inspector">
      <h2>{title}</h2>
      {!d.valid ? (
        <p className="muted">
          No valid prediction here (inside the ground, at the source, outside the terrain, or on a no-data cell). This is not a PASS or a FAIL.
        </p>
      ) : (
        <>
          <p>
            {hasLimits && (
              <strong className={d.code === 1 ? "okc" : d.code === 0 ? "badc" : "muted"}>
                {d.code === 1 ? "PASS" : d.code === 0 ? "FAIL" : "NO DATA"}
              </strong>
            )}{" "}
            Broadband L_p {fmt(d.bb)} dB, L_p,A {fmt(d.bbA)} dB(A) (63-8000 Hz bands). Path: {kindName(d.kind)}.
            {d.code === 0 && d.worstBand > 0 && (
              <> Worst exceedance {BANDS[d.worstBand - 1]} Hz by {fmt(d.worstMargin)} dB.</>
            )}
            {d.overallExceed && <> Overall dB(A) limit exceeded by {fmt(d.overallMargin)} dB.</>}
          </p>
          <SpectrumChart
            predicted={pred}
            label={weighting === "A" ? "L_p,A, dB(A)" : "L_p, dB"}
            limits={limits}
            exceed={d.exceed ?? undefined}
            height={240}
          />
          <table>
            <thead>
              <tr><th>Hz</th><th>Permitted</th><th>Predicted</th><th>Margin</th><th>A_gr</th><th>A_bar</th></tr>
            </thead>
            <tbody>
              {BANDS.map((f, i) => (
                <tr key={f} className={d.exceed?.[i] ? "exc" : ""}>
                  <td>{f}</td>
                  <td>{limits[i] == null ? "-" : limits[i]!.toFixed(1)}</td>
                  <td>{fmt(pred[i])}</td>
                  <td>{d.margin?.[i] == null ? "-" : (d.margin[i]! > 0 ? "+" : "") + d.margin[i]!.toFixed(1)}</td>
                  <td>{fmt(d.Agr[i], 2)}</td>
                  <td>{fmt(d.Abar[i], 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">Margin = predicted - permitted (positive = exceedance). Bands shown in red exceed their limit.</p>
        </>
      )}
    </div>
  );
}
