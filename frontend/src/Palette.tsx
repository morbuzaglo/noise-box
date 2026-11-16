import { useEffect, useMemo, useRef, useState } from "react";
import { IconSearch } from "./icons";
import { Modal } from "./ui";

export interface Command { id: string; label: string; group: string; hint?: string; run: () => void }

// Parameters are discovered from the live parameter panel (every .field / .band label), so the search can never
// drift from the controls that actually exist. Picking one opens its section, scrolls to it and focuses the input.
export function collectParams(root: HTMLElement | null): Command[] {
  if (!root) return [];
  const out: Command[] = [];
  root.querySelectorAll<HTMLElement>(".field, .band").forEach((el, i) => {
    const input = el.querySelector<HTMLElement>("input, select, textarea");
    if (!input) return;
    const sec = el.closest("details.sec");
    const secName = sec?.querySelector("summary")?.firstChild?.textContent?.trim() ?? "Parameters";
    const base = (el.querySelector("span")?.textContent ?? "").trim();
    const label = el.classList.contains("band") ? `Source spectrum ${base} Hz` : base;
    if (!label) return;
    out.push({
      id: `param-${i}`, label, group: secName,
      run: () => {
        if (sec) (sec as HTMLDetailsElement).open = true;
        input.scrollIntoView({ block: "center" });
        input.focus();
        if (input instanceof HTMLInputElement && input.type !== "checkbox") input.select(); // typing replaces the value
        el.classList.add("hl");
        setTimeout(() => el.classList.remove("hl"), 1400);
      },
    });
  });
  return out;
}

export default function Palette({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  const hits = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    return commands.filter((c) => terms.every((t) => `${c.label} ${c.group}`.toLowerCase().includes(t))).slice(0, 40);
  }, [q, commands]);
  useEffect(() => setSel(0), [q]);
  useEffect(() => { listRef.current?.children[sel]?.scrollIntoView({ block: "nearest" }); }, [sel]);
  const go = (c?: Command) => { if (!c) return; onClose(); setTimeout(c.run, 0); };
  return (
    <Modal title="Command palette" onClose={onClose} className="palette">
      <div style={{ display: "flex", alignItems: "center", paddingLeft: 12 }}>
        <IconSearch />
        <input
          placeholder="Search parameters, views and actions"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          role="combobox" aria-expanded="true" aria-controls="palette-list" aria-label="Search parameters, views and actions"
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, hits.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            else if (e.key === "Enter") go(hits[sel]);
          }}
        />
      </div>
      <ul id="palette-list" role="listbox" ref={listRef}>
        {hits.map((c, i) => (
          <li key={c.id} role="option" aria-selected={i === sel} onMouseEnter={() => setSel(i)} onClick={() => go(c)}>
            <span>{c.label}</span>
            {c.hint && <kbd>{c.hint}</kbd>}
            <span className="grp">{c.group}</span>
          </li>
        ))}
      </ul>
      {hits.length === 0 && <div className="none">No matching parameter, view or action.</div>}
    </Modal>
  );
}
