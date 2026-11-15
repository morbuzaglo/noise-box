import { useState } from "react";
import { CaseRow, ProjectRow, createCase, listProjects, runStoredCase, updateCase } from "./api";

export interface Active {
  project: ProjectRow | null;
}

// "Save as case" for any view. `build` returns the exact request the view sends to its endpoint.
// When the view was opened FROM a stored case, `editing` + `buildEdit` add "Save changes and rerun", which
// updates that case in place (its old result is cleared and recomputed with the new inputs).
export default function SaveCase({
  kind, build, project, defaultName, editing, buildEdit,
}: {
  kind: CaseRow["kind"];
  build: () => Record<string, unknown>;
  project: ProjectRow | null;
  defaultName: string;
  editing?: { id: string; name: string } | null;
  buildEdit?: () => Record<string, unknown>;
}) {
  const [name, setName] = useState(defaultName);
  const [msg, setMsg] = useState<string | null>(null);

  async function save() {
    setMsg(null);
    try {
      let p = project;
      if (!p) {
        const all = await listProjects();
        p = all[0] ?? null;
      }
      if (!p) {
        setMsg("Create a project first (Projects page).");
        return;
      }
      const c = await createCase(p.id, name, kind, build());
      setMsg(`Saved case "${c.name}" in project "${p.name}". Open it from the Projects page.`);
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function saveChanges() {
    if (!editing || !buildEdit) return;
    setMsg("Saving and rerunning...");
    try {
      await updateCase(editing.id, buildEdit());
      const done = await runStoredCase(editing.id);
      setMsg(`Case "${done.name}" updated and rerun (${done.status}).`);
    } catch (e) {
      setMsg(String(e));
    }
  }

  return (
    <span className="savecase">
      {editing && buildEdit && <button className="primary" title={`Update "${editing.name}" and rerun it`} onClick={() => void saveChanges()}>Save changes and rerun</button>}
      <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Case name" style={{ width: 150 }} />
      <button onClick={() => void save()}>{editing ? "Save as new case" : "Save as case"}</button>
      {msg && <span className="note">{msg}</span>}
    </span>
  );
}
