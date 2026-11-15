import { useEffect, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { AudioAnalysis, AudioAnalysisRequest, AudioInfo, BANDS, Waveform, analyzeAudio, getWaveform, uploadAudio } from "./api";
import SpectrumChart from "./SpectrumChart";

interface Props {
  G: { Gs: number; Gm: number; Gr: number };
  atm: { T_C: number; RH: number; p_kPa: number };
  onUse: (lw: number[]) => void;
}

const arr = (v: string[] | string | undefined): string[] => (v == null ? [] : Array.isArray(v) ? v : [v]);
const fmt = (v: number | null | undefined, n = 1) => (v == null || !Number.isFinite(v) ? "no data" : v.toFixed(n));
type CalMode = "none" | "sensitivity" | "calibrator";

export default function AudioView({ G, atm, onUse }: Props) {
  const [rec, setRec] = useState<AudioInfo | null>(null);
  const [wf, setWf] = useState<Waveform | null>(null);
  const [sel, setSel] = useState<[number, number]>([0, 1]);
  const [cal, setCal] = useState<CalMode>("none");
  const [pa, setPa] = useState(20);
  const [calRec, setCalRec] = useState<AudioInfo | null>(null);
  const [calInt, setCalInt] = useState({ start: 0, stop: 5, level: 94, freq: 1000 });
  const [bgRec, setBgRec] = useState<AudioInfo | null>(null);
  const [bgInt, setBgInt] = useState({ start: 0, stop: 5 });
  const [geom, setGeom] = useState({ hs: 1.5, hm: 1.2, dp: 10, dh: 0, srcDim: "" });
  const [Dc, setDc] = useState<string[]>(Array(8).fill("0"));
  const [res, setRes] = useState<AudioAnalysis | null>(null);
  const [over, setOver] = useState<string[]>(Array(8).fill(""));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const plot = useRef<HTMLDivElement>(null);
  const player = useRef<HTMLAudioElement>(null);

  async function load(f: File, which: "main" | "cal" | "bg") {
    setErr(null);
    try {
      const info = await uploadAudio(f);
      if (which === "main") {
        setRec(info);
        setSel([0, Math.min(info.duration, 10)]);
        setWf(await getWaveform(info.audio_id, 1, 1500));
        setRes(null);
      } else if (which === "cal") {
        setCalRec(info);
        setCalInt({ ...calInt, start: 0, stop: Math.min(info.duration, 5) });
      } else {
        setBgRec(info);
        setBgInt({ start: 0, stop: Math.min(info.duration, 5) });
      }
    } catch (e) {
      setErr(String(e));
    }
  }

  // waveform with a draggable selection rectangle
  useEffect(() => {
    const el = plot.current;
    if (!el || !wf) return;
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim() || "#222";
    const accent = css.getPropertyValue("--accent").trim() || "#1f5fa8";
    const line = css.getPropertyValue("--line").trim() || "#ddd";
    Plotly.react(
      el,
      [
        { type: "scatter", mode: "lines", x: wf.t, y: wf.max, line: { color: accent, width: 0.8 }, hoverinfo: "skip" },
        { type: "scatter", mode: "lines", x: wf.t, y: wf.min, line: { color: accent, width: 0.8 }, fill: "tonexty", fillcolor: "rgba(31,95,168,0.35)", hoverinfo: "skip" },
      ],
      {
        margin: { l: 52, r: 12, t: 8, b: 40 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", showlegend: false,
        font: { family: "Inter, Segoe UI, sans-serif", size: 12, color: ink },
        xaxis: { title: { text: "Time, s" }, range: [0, wf.duration], gridcolor: line },
        yaxis: { title: { text: "Amplitude, digital units" }, gridcolor: line },
        shapes: [
          { type: "rect", xref: "x", yref: "paper", x0: sel[0], x1: sel[1], y0: 0, y1: 1, fillcolor: "rgba(230,126,34,0.25)", line: { color: "#e67e22", width: 2 }, editable: true } as unknown as Partial<Plotly.Shape>,
        ],
      },
      { displayModeBar: false, responsive: true, edits: { shapePosition: true } },
    );
    const any = el as unknown as { removeAllListeners?: (n: string) => void; on: (n: string, f: (e: Record<string, number>) => void) => void };
    any.removeAllListeners?.("plotly_relayout");
    any.on("plotly_relayout", (e) => {
      const a = e["shapes[0].x0"], b = e["shapes[0].x1"];
      if (a == null && b == null) return;
      const x0 = Math.max(0, Math.min(a ?? sel[0], b ?? sel[1]));
      const x1 = Math.min(wf.duration, Math.max(a ?? sel[0], b ?? sel[1]));
      if (x1 - x0 >= 0.1) setSel([Number(x0.toFixed(3)), Number(x1.toFixed(3))]);
    });
  }, [wf, sel]); // eslint-disable-line react-hooks/exhaustive-deps

  function playSelection() {
    const a = player.current;
    if (!a) return;
    a.currentTime = sel[0];
    void a.play();
    const stop = () => {
      if (a.currentTime >= sel[1]) {
        a.pause();
        a.removeEventListener("timeupdate", stop);
      }
    };
    a.addEventListener("timeupdate", stop);
  }

  async function analyse() {
    if (!rec) return;
    setBusy(true);
    setErr(null);
    const req: AudioAnalysisRequest = {
      signal: { audio_id: rec.audio_id, start: sel[0], stop: sel[1] },
      calibration:
        cal === "none" ? { mode: "none" }
        : cal === "sensitivity" ? { mode: "sensitivity", pa_per_unit: pa }
        : { mode: "calibrator", calibrator: { audio_id: calRec?.audio_id ?? "", start: calInt.start, stop: calInt.stop, level: calInt.level, freq: calInt.freq } },
      background: bgRec ? { audio_id: bgRec.audio_id, start: bgInt.start, stop: bgInt.stop } : undefined,
      estimate: cal !== "none"
        ? { hs: geom.hs, hm: geom.hm, dp: geom.dp, dh: geom.dh, G, atm, Dc: Dc.map(parseFloat), srcDim: geom.srcDim.trim() === "" ? undefined : parseFloat(geom.srcDim) }
        : undefined,
    };
    try {
      const r = await analyzeAudio(req);
      setRes(r);
      setOver((r.lw?.Lw ?? Array(8).fill(null)).map((v) => (v == null ? "" : v.toFixed(1))));
    } catch (e) {
      setErr(String(e));
      setRes(null);
    } finally {
      setBusy(false);
    }
  }

  const overNum = over.map((s) => (s.trim() === "" ? NaN : parseFloat(s)));
  const usable = res?.absolute && overNum.every((v) => Number.isFinite(v));
  const warnings = useMemo(() => [...arr(res?.warnings), ...arr(res?.calibration?.warnings), ...arr(res?.lw?.warnings)], [res]);

  return (
    <div>
      <h2>Measured recording</h2>
      <p className="note">
        A raw digital recording is not a calibrated sound pressure. Without a calibration the octave levels are relative only, and absolute L_p and L_W are disabled.
        One microphone in one direction gives an apparent L_W, not the true sound power.
      </p>
      <label className="field"><span>Recording (WAV, FLAC, OGG)</span>
        <input type="file" accept=".wav,.flac,.ogg,.mp3,.aif,.aiff" onChange={(e) => { const f = e.target.files?.[0]; if (f) void load(f, "main"); }} />
      </label>
      {err && <div className="error">{err}</div>}
      {rec && wf && (
        <>
          <p className="note">{rec.name}: {rec.duration.toFixed(2)} s, {rec.fs} Hz, {rec.channels} channel(s), peak {rec.peak.toFixed(3)} (full scale = 1).</p>
          <audio ref={player} controls src={`/api/audio/${rec.audio_id}/file`} style={{ width: "100%" }} />
          <div ref={plot} style={{ width: "100%", height: 200 }} />
          <div className="tabs">
            <label className="field"><span>Start, s</span><input type="number" step={0.1} value={sel[0]} onChange={(e) => setSel([Math.max(0, parseFloat(e.target.value)), sel[1]])} /></label>
            <label className="field"><span>End, s</span><input type="number" step={0.1} value={sel[1]} onChange={(e) => setSel([sel[0], Math.min(rec.duration, parseFloat(e.target.value))])} /></label>
            <button onClick={playSelection}>Play selection</button>
            <span className="note">Drag the orange region on the waveform or type the times. Selection {(sel[1] - sel[0]).toFixed(2)} s.</span>
          </div>

          <div className="scene">
            <div>
              <h2>Calibration</h2>
              <label className="field"><span>Level reference</span>
                <select value={cal} onChange={(e) => setCal(e.target.value as CalMode)}>
                  <option value="none">None (relative levels only)</option>
                  <option value="sensitivity">Known sensitivity, Pa per digital unit</option>
                  <option value="calibrator">Recorded acoustic calibrator</option>
                </select>
              </label>
              {cal === "sensitivity" && (
                <label className="field"><span>Pa per digital unit</span><span className="inputwrap"><input type="number" value={pa} onChange={(e) => setPa(parseFloat(e.target.value))} /><em>Pa</em></span></label>
              )}
              {cal === "calibrator" && (
                <>
                  <label className="field"><span>Calibrator recording</span>
                    <input type="file" accept=".wav,.flac,.ogg" onChange={(e) => { const f = e.target.files?.[0]; if (f) void load(f, "cal"); }} /></label>
                  {calRec && <p className="note">{calRec.name}: {calRec.duration.toFixed(1)} s, {calRec.fs} Hz</p>}
                  {(["start", "stop", "level", "freq"] as const).map((k) => (
                    <label key={k} className="field"><span>{k === "level" ? "Calibrator level, dB" : k === "freq" ? "Calibrator frequency, Hz" : `Tone ${k}, s`}</span>
                      <input type="number" value={calInt[k]} onChange={(e) => setCalInt({ ...calInt, [k]: parseFloat(e.target.value) })} /></label>
                  ))}
                  <p className="note">Same microphone and gain settings as the measurement.</p>
                </>
              )}
              <h2>Background noise (optional)</h2>
              <label className="field"><span>Background-only recording</span>
                <input type="file" accept=".wav,.flac,.ogg" onChange={(e) => { const f = e.target.files?.[0]; if (f) void load(f, "bg"); }} /></label>
              {bgRec && (["start", "stop"] as const).map((k) => (
                <label key={k} className="field"><span>Background {k}, s</span>
                  <input type="number" value={bgInt[k]} onChange={(e) => setBgInt({ ...bgInt, [k]: parseFloat(e.target.value) })} /></label>
              ))}
            </div>
            <div>
              <h2>Measurement geometry</h2>
              {(["hs", "hm", "dp", "dh"] as const).map((k) => (
                <label key={k} className="field">
                  <span>{k === "hs" ? "Source height above ground" : k === "hm" ? "Microphone height above ground" : k === "dp" ? "Horizontal distance source-microphone" : "Ground elevation, mic minus source"}</span>
                  <span className="inputwrap"><input type="number" step={0.1} value={geom[k]} onChange={(e) => setGeom({ ...geom, [k]: parseFloat(e.target.value) })} /><em>m</em></span>
                </label>
              ))}
              <label className="field"><span>Largest source dimension (optional)</span><span className="inputwrap"><input type="number" value={geom.srcDim} onChange={(e) => setGeom({ ...geom, srcDim: e.target.value })} /><em>m</em></span></label>
              <p className="note">Ground factors and atmosphere come from the left panel. Directivity correction toward the microphone, D_c per band (dB):</p>
              <div className="bands">
                {BANDS.map((f, i) => (
                  <label key={f} className="band"><span>{f}</span>
                    <input type="number" step={0.5} value={Dc[i]} onChange={(e) => setDc(Dc.map((v, j) => (j === i ? e.target.value : v)))} /></label>
                ))}
              </div>
            </div>
            <div>
              <h2>Analysis</h2>
              <button className="primary" disabled={busy || sel[1] - sel[0] < 0.1 || (cal === "calibrator" && !calRec)} onClick={() => void analyse()}>
                {busy ? "Analysing" : "Analyse selection"}
              </button>
              <p className="note">Octave filters: custom 6th-order Butterworth bank (Signal Processing Toolbox), not verified for IEC 61260-1 class conformance.</p>
            </div>
          </div>

          {res && (
            <div className="inspector">
              <h2>{res.absolute ? "Octave-band sound pressure level, dB re 20 uPa (unweighted)" : "Relative octave-band levels, dB re one digital RMS unit"}</h2>
              {!res.absolute && <div className="error">No calibration: these are relative levels. Absolute L_p and L_W are disabled and cannot be used for a prediction.</div>}
              <SpectrumChart predicted={res.Lused} label={res.absolute ? "L_p, dB re 20 uPa" : "relative level, dB"} height={240} />
              <table>
                <thead><tr><th>Hz</th><th>Measured</th>{res.subtraction && <><th>Background corrected</th><th>Delta L</th><th>Validity</th></>}{res.lw && <><th>A (div+atm+gr)</th><th>Apparent L_W</th></>}</tr></thead>
                <tbody>
                  {BANDS.map((f, i) => (
                    <tr key={f} className={res.subtraction?.status[i] === "invalid" ? "exc" : ""}>
                      <td>{f}</td><td>{fmt(res.L[i])}</td>
                      {res.subtraction && <><td>{fmt(res.subtraction.Lcorr[i])}</td><td>{fmt(res.subtraction.deltaL[i])}</td><td>{res.subtraction.status[i]}</td></>}
                      {res.lw && <><td>{fmt(res.lw.A[i], 2)}</td><td>{fmt(res.lw.Lw[i])}</td></>}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note">{res.signal.noteBroadband} Broadband (analysed bands): {fmt(res.signal.broadband)} dB.</p>
              {res.calibration && <p className="note">{res.calibration.note} Sensitivity {res.calibration.paPerUnit.toFixed(3)} Pa per unit, tone-to-total {res.calibration.toneToTotal_dB.toFixed(1)} dB.</p>}
              {warnings.length > 0 && <ul className="note">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
              {res.lw && (
                <>
                  <h2>Source sound power L_W (editable before use)</h2>
                  <div className="bands">
                    {BANDS.map((f, i) => (
                      <label key={f} className="band"><span>{f}</span>
                        <input type="number" step={0.1} value={over[i]} onChange={(e) => setOver(over.map((v, j) => (j === i ? e.target.value : v)))} /></label>
                    ))}
                  </div>
                  <p className="note">Apparent sound power level, dB re 1 pW, unweighted. Bands with no valid level are empty and must be filled by hand before use.</p>
                  <button className="primary" disabled={!usable} onClick={() => onUse(overNum)}>Use as source spectrum</button>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
