const BASE = "http://localhost:8000/api";

export interface Project {
  id: number;
  name: string;
  directory_path: string;
  last_synced_at: string | null;
}

export interface TestRequest {
  id: number;
  natural_instruction: string;
  generated_cypress_code: string;
  created_at: string;
}

export async function getProjects(): Promise<Project[]> {
  const res = await fetch(`${BASE}/projects/`);
  const data = await res.json();
  return data.projects;
}

export async function createProject(name: string, directory_path: string): Promise<Project> {
  const res = await fetch(`${BASE}/projects/create/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, directory_path }),
  });
  return res.json();
}

export async function syncProject(projectId: number): Promise<{ chunks_indexed: number }> {
  const res = await fetch(`${BASE}/projects/${projectId}/sync/`, { method: "POST" });
  return res.json();
}

export async function generateTest(
  projectId: number,
  instruction: string
): Promise<{ test_request_id: number; cypress_code: string }> {
  const res = await fetch(`${BASE}/projects/${projectId}/generate/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  });
  return res.json();
}

export async function getTestRequests(projectId: number): Promise<TestRequest[]> {
  const res = await fetch(`${BASE}/projects/${projectId}/tests/`);
  const data = await res.json();
  return data.test_requests;
}

export async function pickDirectory(): Promise<string> {
  const res = await fetch(`${BASE}/pick-directory/`);
  const data = await res.json();
  return data.path ?? "";
}
