import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { BANDS } from "./api";

interface Props {
  predicted: (number | null)[];
  label: string;
  limits?: (number | null)[];
  exceed?: boolean[]; // bars with a true entry are drawn in the alert colour
  height?: number;
}

// Octave-band levels on a categorical x axis (bands are log-spaced, so labels, not a numeric axis).
export default function SpectrumChart({ predicted, label, limits, exceed, height }: Props) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current) return;
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim() || "#222";
    const accent = css.getPropertyValue("--accent").trim() || "#1f5fa8";
    const grid = css.getPropertyValue("--line").trim() || "#ddd";
    const x = BANDS.map(String);
    const bad = css.getPropertyValue("--bad").trim() || "#a32020";
    const colors = predicted.map((_, i) => (exceed && exceed[i] ? bad : accent));
    const traces: Plotly.Data[] = [
      { x, y: predicted as number[], type: "bar", name: label, marker: { color: colors } },
    ];
    if (limits) {
      traces.push({
        x,
        y: limits as number[],
        type: "scatter",
        mode: "lines+markers",
        name: "Permitted level",
        connectgaps: false,
        line: { color: ink, dash: "dot" },
      });
    }
    Plotly.react(
      el.current,
      traces,
      {
        margin: { l: 52, r: 12, t: 8, b: 44 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Inter, Segoe UI, sans-serif", size: 12, color: ink },
        xaxis: { title: { text: "Octave band centre frequency, Hz" }, gridcolor: grid, type: "category" },
        yaxis: { title: { text: label }, gridcolor: grid, zeroline: false },
        legend: { orientation: "h", y: -0.28 },
      },
      { displayModeBar: false, responsive: true },
    );
  }, [predicted, label, limits, exceed]);
  return <div ref={el} style={{ width: "100%", height: height ?? 300 }} />;
}
