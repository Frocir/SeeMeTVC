const TOKEN_KEY = "seemetvc_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : "请求失败");
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export type Me = {
  id: number;
  email: string;
  display_name: string;
  role: string;
  balance: number;
  is_active: boolean;
  balance_unit: string;
};

export type ModelOption = {
  model_id: string;
  cost_per_second: number;
  provider: string;
};

export type Job = {
  id: number;
  model_id: string;
  prompt: string;
  image_url: string | null;
  duration_seconds: number;
  status: string;
  cost: number;
  balance_after: number | null;
  result_url: string | null;
  error_message: string | null;
  created_at: string;
};

export type ParallelQuota = {
  max_parallel: number;
  active: number;
  available: number;
};

export const STATUS_LABEL: Record<string, string> = {
  pending: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
  refunded: "已退款",
};

export function isActiveJob(status: string) {
  return status === "pending" || status === "running";
}

export function isTerminalJob(status: string) {
  return status === "succeeded" || status === "failed" || status === "refunded";
}

export type Channel = {
  id: number;
  name: string;
  provider: string;
  base_url: string;
  model_id: string;
  upstream_model: string;
  cost_per_second: number;
  priority: number;
  enabled: boolean;
  remark: string;
  api_key_masked: string;
};

export type AdminUser = {
  id: number;
  email: string;
  display_name: string;
  role: string;
  balance: number;
  is_active: boolean;
};

export type WorkflowGraph = {
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
};

export type Workflow = {
  id: number;
  name: string;
  graph: WorkflowGraph;
  created_at: string;
  updated_at: string;
};

export type WorkflowNodeState = {
  status: string;
  output?: Record<string, unknown> | null;
  error?: string | null;
  cost?: number;
};

export type WorkflowRun = {
  id: number;
  workflow_id: number | null;
  status: string;
  graph: WorkflowGraph;
  node_states: Record<string, WorkflowNodeState>;
  cost: number;
  balance_after: number | null;
  result_url: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export function isActiveRun(status: string) {
  return status === "pending" || status === "running";
}

export function isTerminalRun(status: string) {
  return status === "succeeded" || status === "failed" || status === "refunded";
}

export type UploadImageResult = {
  url: string;
  filename: string;
  size: number;
};

/** Multipart upload for reference images; returns a same-origin /uploads/... URL. */
export async function uploadImage(file: File): Promise<UploadImageResult> {
  const body = new FormData();
  body.append("file", file);
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch("/api/uploads/images", { method: "POST", headers, body });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : "上传失败");
  }
  return res.json();
}
