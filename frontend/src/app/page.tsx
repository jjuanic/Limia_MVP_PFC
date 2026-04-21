"use client";

import { useState, useEffect } from "react";
import { getProjects, createProject, syncProject, generateTest, pickDirectory, Project } from "../lib/api";

function stripFences(code: string): string {
  return code.replace(/^```[\w]*\n?/, "").replace(/\n?```\s*$/, "").trim();
}

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);

  const [newName, setNewName] = useState("");
  const [newPath, setNewPath] = useState("");
  const [creating, setCreating] = useState(false);

  const [instruction, setInstruction] = useState("");
  const [generatedCode, setGeneratedCode] = useState("");
  const [generating, setGenerating] = useState(false);

  const [syncMsg, setSyncMsg] = useState("");
  const [syncing, setSyncing] = useState(false);

  const MIN_INSTRUCTION = 20;

  const [copied, setCopied] = useState(false);

  useEffect(() => { getProjects().then(setProjects); }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    const p = await createProject(newName, newPath);
    setProjects((prev) => [...prev, p as Project]);
    setNewName("");
    setNewPath("");
    setCreating(false);
  }

  async function handleSync() {
    if (!selected) return;
    setSyncing(true);
    setSyncMsg("");
    const res = await syncProject(selected.id);
    const updated = await getProjects();
    setProjects(updated);
    setSelected(updated.find((p) => p.id === selected.id) ?? selected);
    setSyncMsg(`${res.chunks_indexed} chunks indexed`);
    setSyncing(false);
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || !instruction) return;
    setGenerating(true);
    setGeneratedCode("");
    const res = await generateTest(selected.id, instruction);
    setGeneratedCode(stripFences(res.cypress_code));
    setGenerating(false);
  }

  function handleCopy() {
    navigator.clipboard.writeText(generatedCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function selectProject(p: Project) {
    setSelected(p);
    setSyncMsg("");
    setGeneratedCode("");
  }

  return (
    <div className="app-shell">
      {/* Header */}
      <header className="app-header">
        <span style={{ fontSize: 20 }}>🧪</span>
        <h1>Cypress Test Generator</h1>
      </header>

      <div className="app-body">
        {/* Sidebar */}
        <aside className="sidebar">
          {/* Add project */}
          <div className="card">
            <div className="card-title">Add Project</div>
            <form onSubmit={handleCreate}>
              <div className="input-row">
                <label className="label">Name</label>
                <input
                  className="input"
                  placeholder="My App"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  required
                />
              </div>
              <div className="input-row">
                <label className="label">Directory path</label>
                <div className="path-row">
                  <input
                    className="input"
                    placeholder="C:\path\to\project"
                    value={newPath}
                    onChange={(e) => setNewPath(e.target.value)}
                    required
                  />
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={async () => { const p = await pickDirectory(); if (p) setNewPath(p); }}
                  >
                    Browse
                  </button>
                </div>
              </div>
              <button className="btn btn-primary btn-full" type="submit" disabled={creating}>
                {creating ? "Adding…" : "+ Add"}
              </button>
            </form>
          </div>

          {/* Project list */}
          <div className="card" style={{ flex: 1 }}>
            <div className="card-title">Projects</div>
            {projects.length === 0 ? (
              <p className="empty">No projects yet.</p>
            ) : (
              <ul className="project-list" style={{ listStyle: "none" }}>
                {projects.map((p) => (
                  <li
                    key={p.id}
                    className={`project-item${selected?.id === p.id ? " active" : ""}`}
                    onClick={() => selectProject(p)}
                  >
                    <div className="project-name">{p.name}</div>
                    <div className="project-path">{p.directory_path}</div>
                    {p.last_synced_at && (
                      <span className="synced-badge">
                        synced {new Date(p.last_synced_at).toLocaleDateString()}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* Main area */}
        <main className="main">
          {!selected ? (
            <div className="placeholder">
              <div className="placeholder-icon">←</div>
              <p>Select a project to get started</p>
            </div>
          ) : (
            <>
              {/* Sync */}
              <div className="card">
                <div className="card-title">Sync — {selected.name}</div>
                <p style={{ color: "var(--muted)", marginBottom: "1rem", fontSize: 13 }}>
                  Scans the directory, chunks source files and indexes them into ChromaDB.
                </p>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <button className="btn btn-secondary" onClick={handleSync} disabled={syncing}>
                    {syncing ? "Syncing…" : "⟳  Sync Project"}
                  </button>
                  {syncMsg && <span className="status-msg">✓ {syncMsg}</span>}
                </div>
              </div>

              {/* Generate */}
              <div className="card">
                <div className="card-title">Generate Test</div>
                <form onSubmit={handleGenerate}>
                  <div className="input-row">
                    <label className="label">Natural-language instruction</label>
                    <textarea
                      className="input"
                      placeholder='e.g. "Open the login page, enter valid credentials and verify the dashboard appears."'
                      value={instruction}
                      onChange={(e) => setInstruction(e.target.value)}
                      required
                    />
                    {instruction.length > 0 && instruction.length < MIN_INSTRUCTION && (
                      <span style={{ fontSize: 12, color: "var(--muted)" }}>
                        {MIN_INSTRUCTION - instruction.length} more characters needed
                      </span>
                    )}
                  </div>
                  <button
                    className="btn btn-primary"
                    type="submit"
                    disabled={generating || instruction.length < MIN_INSTRUCTION}
                  >
                    {generating ? "Generating…" : "▶  Generate"}
                  </button>
                </form>
              </div>

              {/* Output */}
              {generatedCode && (
                <div className="card">
                  <div className="card-title">Generated Cypress Script</div>
                  <div className="code-block-wrapper">
                    <button
                      className="btn btn-secondary btn-sm copy-btn"
                      onClick={handleCopy}
                    >
                      {copied ? "✓ Copied" : "Copy"}
                    </button>
                    <pre className="code-block">{generatedCode}</pre>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
