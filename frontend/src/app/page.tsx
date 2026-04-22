"use client";

import { useState, useEffect, useRef } from "react";
import {
  getProjects, createProject, syncProject, generateTest,
  pickDirectory, Project, GenerateError,
} from "../lib/api";

const MIN_INSTRUCTION = 1;

function stripFences(code: string): string {
  const match = code.match(/```[\w]*\n?([\s\S]*?)\n?```/);
  if (match) return match[1].trim();
  return code.replace(/^```[\w]*\n?/, "").replace(/\n?```\s*$/, "").trim();
}

type MsgType = "code" | "plan" | "chat" | "error" | "system";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  type: MsgType;
  content: string;
}

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);

  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newPath, setNewPath] = useState("");
  const [creating, setCreating] = useState(false);

  const [chatHistory, setChatHistory] = useState<Record<number, ChatMessage[]>>({});
  const [instruction, setInstruction] = useState("");
  const [generating, setGenerating] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const messages: ChatMessage[] = selected ? (chatHistory[selected.id] ?? []) : [];

  useEffect(() => { getProjects().then(setProjects); }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, generating]);

  function addMessage(projectId: number, msg: Omit<ChatMessage, "id">) {
    const id = crypto.randomUUID();
    setChatHistory(prev => ({
      ...prev,
      [projectId]: [...(prev[projectId] ?? []), { ...msg, id }],
    }));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    const p = await createProject(newName, newPath);
    setProjects(prev => [...prev, p as Project]);
    setNewName("");
    setNewPath("");
    setCreating(false);
    setShowAddForm(false);
  }

  async function handleSync() {
    if (!selected) return;
    setSyncing(true);
    const res = await syncProject(selected.id);
    const updated = await getProjects();
    setProjects(updated);
    setSelected(updated.find(p => p.id === selected.id) ?? selected);
    addMessage(selected.id, {
      role: "assistant",
      type: "system",
      content: `Project synced — ${res.chunks_indexed} chunks indexed.`,
    });
    setSyncing(false);
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || instruction.length < MIN_INSTRUCTION || generating) return;

    const text = instruction.trim();
    setInstruction("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    abortRef.current = new AbortController();
    setGenerating(true);

    addMessage(selected.id, { role: "user", type: "code", content: text });

    try {
      const res = await generateTest(selected.id, text, abortRef.current.signal);

      if ("error" in (res as GenerateError)) {
        addMessage(selected.id, {
          role: "assistant",
          type: "error",
          content: (res as GenerateError).error,
        });
      } else {
        const r = res as Exclude<typeof res, GenerateError>;
        addMessage(selected.id, {
          role: "assistant",
          type: r.response_type,
          content: r.response_type === "code"
            ? stripFences(r.cypress_code)
            : r.cypress_code.replace(/^CHAT:\s*/, "").replace(/^PLAN_NEEDED:\n?/, ""),
        });
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        addMessage(selected.id, { role: "assistant", type: "error", content: "Request failed." });
      }
    }

    setGenerating(false);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate(e as unknown as React.FormEvent);
    }
  }

  function handleTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInstruction(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px";
  }

  function handleCopy(id: string, content: string) {
    navigator.clipboard.writeText(content);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  function selectProject(p: Project) {
    setSelected(p);
    setInstruction("");
  }

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-top">
          <span className="sidebar-logo">🍋</span>
          <span className="sidebar-title">Limia</span>
        </div>

        <div className="sidebar-section-label">Projects</div>

        <div className="sidebar-projects">
          {projects.length === 0 ? (
            <p className="sidebar-empty">No projects yet.</p>
          ) : (
            projects.map(p => (
              <div
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
              </div>
            ))
          )}
        </div>

        <div className="sidebar-footer">
          {showAddForm ? (
            <form onSubmit={handleCreate} className="add-form">
              <input
                className="input"
                placeholder="Project name"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                required
              />
              <div className="path-row">
                <input
                  className="input"
                  placeholder="C:\path\to\project"
                  value={newPath}
                  onChange={e => setNewPath(e.target.value)}
                  required
                />
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={async () => { const p = await pickDirectory(); if (p) setNewPath(p); }}
                >
                  …
                </button>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn btn-primary btn-full" type="submit" disabled={creating}>
                  {creating ? "Adding…" : "Add"}
                </button>
                <button className="btn btn-secondary" type="button" onClick={() => setShowAddForm(false)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button className="btn btn-secondary btn-full" onClick={() => setShowAddForm(true)}>
              + New Project
            </button>
          )}
        </div>
      </aside>

      {/* ── Chat area ── */}
      <div className="chat-area">
        {!selected ? (
          <div className="chat-empty">
            <div className="chat-empty-icon">🍋</div>
            <p className="chat-empty-title">Limia</p>
            <p className="chat-empty-sub">Select a project from the sidebar to start.</p>
          </div>
        ) : (
          <>
            <div className="chat-header">
              <div className="chat-header-info">
                <span className="chat-header-name">{selected.name}</span>
                <span className="chat-header-path">{selected.directory_path}</span>
              </div>
              <button className="btn btn-secondary btn-sm" onClick={handleSync} disabled={syncing}>
                {syncing ? "Syncing…" : "⟳ Sync"}
              </button>
            </div>

            <div className="chat-messages">
              {messages.length === 0 && (
                <div className="chat-hint">
                  {selected.last_synced_at
                    ? "Describe what you want to test."
                    : "Sync the project first, then describe what you want to test."}
                </div>
              )}

              {messages.map(msg => (
                <div key={msg.id} className={`msg msg-${msg.role}`}>
                  {msg.role === "user" ? (
                    <div className="msg-user-bubble">{msg.content}</div>
                  ) : msg.type === "system" ? (
                    <div className="msg-system">{msg.content}</div>
                  ) : msg.type === "error" ? (
                    <div className="msg-error">{msg.content}</div>
                  ) : msg.type === "chat" ? (
                    <div className="msg-chat">{msg.content}</div>
                  ) : msg.type === "plan" ? (
                    <div className="msg-plan">
                      <div className="msg-plan-header">Could not generate the test</div>
                      <pre className="msg-plan-body">
                        {msg.content.replace(/^PLAN_NEEDED:\n?/, "").trimStart()}
                      </pre>
                    </div>
                  ) : (
                    <div className="msg-code-wrapper">
                      <div className="msg-code-header">
                        <span>Cypress test</span>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleCopy(msg.id, msg.content)}
                        >
                          {copiedId === msg.id ? "✓ Copied" : "Copy"}
                        </button>
                      </div>
                      <pre className="code-block">{msg.content}</pre>
                    </div>
                  )}
                </div>
              ))}

              {generating && (
                <div className="msg msg-assistant">
                  <div className="msg-thinking">
                    <span /><span /><span />
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            <div className="chat-input-bar">
              <form onSubmit={handleGenerate} className="chat-input-form">
                <div className="chat-input-wrapper">
                  <textarea
                    ref={textareaRef}
                    className="chat-textarea"
                    placeholder="Describe what you want to test… (Enter to send, Shift+Enter for newline)"
                    value={instruction}
                    onChange={handleTextareaChange}
                    onKeyDown={handleKeyDown}
                    rows={1}
                  />
                  {generating ? (
                    <button
                      className="btn btn-secondary chat-send-btn"
                      type="button"
                      onClick={() => { abortRef.current?.abort(); setGenerating(false); }}
                    >
                      ■
                    </button>
                  ) : (
                    <button
                      className="btn btn-primary chat-send-btn"
                      type="submit"
                      disabled={instruction.length < MIN_INSTRUCTION}
                    >
                      ↑
                    </button>
                  )}
                </div>
              </form>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
