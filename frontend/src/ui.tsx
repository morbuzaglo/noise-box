import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

// ---------- toasts (module-level so any view can call toast()) ----------
type Tone = "info" | "ok" | "bad";
interface ToastItem { id: number; msg: string; tone: Tone }
let nextId = 1;
let push: ((t: ToastItem) => void) | null = null;
export function toast(msg: string, tone: Tone = "info") {
  push?.({ id: nextId++, msg, tone });
}
export function Toasts() {
  const [items, setItems] = useState<ToastItem[]>([]);
  useEffect(() => {
    push = (t) => {
      setItems((a) => [...a.slice(-3), t]);
      setTimeout(() => setItems((a) => a.filter((x) => x.id !== t.id)), t.tone === "bad" ? 7000 : 3500);
    };
    return () => { push = null; };
  }, []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => <div key={t.id} className={`toast ${t.tone === "info" ? "" : t.tone}`}>{t.msg}</div>)}
    </div>
  );
}

// ---------- modal dialog with focus trap-lite (Escape closes, first control focused) ----------
export function Modal({ title, onClose, children, className = "" }: { title: string; onClose: () => void; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, button.primary, button")?.focus();
    return () => prev?.focus?.();
  }, []);
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={`dialog ${className}`} role="dialog" aria-modal="true" aria-label={title} onKeyDown={(e) => e.key === "Escape" && onClose()}>
        {children}
      </div>
    </div>
  );
}

// Replacement for window.confirm / window.prompt. Resolve with the user's answer; no native dialogs block the page.
type Ask = { kind: "confirm"; title: string; text: string; danger?: boolean; ok: (v: boolean) => void } | { kind: "prompt"; title: string; text: string; value: string; ok: (v: string | null) => void };
let openAsk: ((a: Ask) => void) | null = null;
export const confirmDialog = (title: string, text: string) => new Promise<boolean>((ok) => (openAsk ? openAsk({ kind: "confirm", title, text, ok }) : ok(false)));
export const promptDialog = (title: string, text: string, value: string) => new Promise<string | null>((ok) => (openAsk ? openAsk({ kind: "prompt", title, text, value, ok }) : ok(null)));

export function DialogHost() {
  const [ask, setAsk] = useState<Ask | null>(null);
  const [val, setVal] = useState("");
  useEffect(() => {
    openAsk = (a) => { setAsk(a); setVal(a.kind === "prompt" ? a.value : ""); };
    return () => { openAsk = null; };
  }, []);
  const done = useCallback((ok: boolean) => {
    if (!ask) return;
    if (ask.kind === "confirm") ask.ok(ok);
    else ask.ok(ok ? val : null);
    setAsk(null);
  }, [ask, val]);
  if (!ask) return null;
  return (
    <Modal title={ask.title} onClose={() => done(false)}>
      <h3>{ask.title}</h3>
      <p className="note">{ask.text}</p>
      {ask.kind === "prompt" && <input value={val} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === "Enter" && done(true)} aria-label={ask.title} />}
      <div className="actions">
        <button onClick={() => done(false)}>Cancel</button>
        <button className="primary" onClick={() => done(true)}>{ask.kind === "confirm" ? "Confirm" : "OK"}</button>
      </div>
    </Modal>
  );
}
