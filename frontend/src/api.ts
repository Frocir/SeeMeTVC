const TOKEN_KEY = "seemetvc_token";

/** Same-origin by default (`/api` via Vite proxy or nginx). Split deploy: set VITE_API_BASE. */
export function apiUrl(path: string): string {
  const base = String(import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}

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

  const res = await fetch(apiUrl(path), { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    const err = new Error(typeof detail === "string" ? detail : "请求失败") as Error & {
      status: number;
    };
    err.status = res.status;
    throw err;
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
  kind?: string;
  label?: string;
  duration_min?: number;
  duration_max?: number;
  supports_audio?: boolean;
  supports_image?: boolean;
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
  draft: "未出片",
  pending: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
  refunded: "已退款",
  cancelled: "已取消",
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
  kind?: string;
  base_url: string;
  model_id: string;
  upstream_model: string;
  cost_per_second: number;
  priority: number;
  enabled: boolean;
  remark: string;
  api_key_masked: string;
};

export type ChannelProbe = {
  ok: boolean;
  message: string;
  latency_ms: number;
  detail?: string;
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
  kind?: string;
  project?: Record<string, unknown>;
};

export type Workflow = {
  id: number;
  name: string;
  brand?: string;
  cover_url?: string | null;
  graph: WorkflowGraph;
  created_at: string;
  updated_at: string;
};

export type ProjectAsset = {
  id: number;
  workflow_id: number;
  kind: "image" | "video" | "output" | string;
  url: string;
  filename: string;
  created_at: string;
};

export type UploadOut = {
  url: string;
  filename: string;
  size: number;
};

export async function uploadFile(path: string, file: File): Promise<UploadOut> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(apiUrl(path), { method: "POST", headers, body });
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

export type WorkflowNodeState = {
  status: string;
  output?: Record<string, unknown> | null;
  error?: string | null;
  cost?: number;
  hint?: string | null;
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

export type BalanceEntry = {
  id: number;
  amount: number;
  balance_after: number;
  kind: string;
  title: string;
  ref_type: string;
  ref_id: number | null;
  created_at: string;
};

export function isActiveRun(status: string) {
  return status === "pending" || status === "running";
}

export function isTerminalRun(status: string) {
  return (
    status === "succeeded" ||
    status === "failed" ||
    status === "refunded" ||
    status === "cancelled"
  );
}

const POLL_INTERVAL_MS = 1500;

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const t = window.setTimeout(() => resolve(), ms);
    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(t);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

function goneRun(runId: number): WorkflowRun {
  return {
    id: runId,
    workflow_id: null,
    status: "cancelled",
    graph: { nodes: [], edges: [] },
    node_states: {},
    cost: 0,
    balance_after: null,
    result_url: null,
    error_message: null,
    created_at: "",
    updated_at: "",
  };
}

/** Subscribe to workflow run progress via SSE; poll until terminal if SSE fails or ends early. */
export function subscribeWorkflowRun(
  runId: number,
  onUpdate: (run: WorkflowRun) => void | Promise<void>,
  signal?: AbortSignal,
): () => void {
  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort();
  signal?.addEventListener("abort", onAbort);

  let closed = false;
  const stop = () => {
    if (closed) return;
    closed = true;
    ctrl.abort();
    signal?.removeEventListener("abort", onAbort);
  };

  const pollUntilDone = async () => {
    while (!closed) {
      try {
        const fresh = await api<WorkflowRun>(`/api/workflows/runs/${runId}`);
        await onUpdate(fresh);
        if (isTerminalRun(fresh.status)) {
          stop();
          return;
        }
      } catch (e) {
        const status = (e as Error & { status?: number }).status;
        if (status === 404) await onUpdate(goneRun(runId));
        stop();
        return;
      }
      await sleep(POLL_INTERVAL_MS, ctrl.signal);
    }
  };

  void (async () => {
    const token = getToken();
    try {
      const res = await fetch(apiUrl(`/api/workflows/runs/${runId}/events`), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`SSE ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const chunks = buf.split("\n\n");
        buf = chunks.pop() || "";
        for (const chunk of chunks) {
          const lines = chunk.split("\n");
          let event = "message";
          const dataLines: string[] = [];
          for (const line of lines) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;
          if (event === "done") {
            stop();
            return;
          }
          if (event === "error") {
            await onUpdate(goneRun(runId));
            stop();
            return;
          }
          if (event === "run" || event === "message") {
            try {
              const run = JSON.parse(dataLines.join("\n")) as WorkflowRun;
              await onUpdate(run);
              if (isTerminalRun(run.status)) {
                stop();
                return;
              }
            } catch {
              /* ignore bad frame */
            }
          }
        }
      }
      // Stream closed without a terminal/done frame — keep polling.
      if (!closed) await pollUntilDone();
    } catch (e) {
      if (closed || (e instanceof DOMException && e.name === "AbortError")) return;
      try {
        await pollUntilDone();
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
      }
    }
  })();

  return stop;
}

export async function uploadVideo(file: File): Promise<UploadImageResult> {
  const body = new FormData();
  body.append("file", file);
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(apiUrl("/api/uploads/videos"), { method: "POST", headers, body });
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

export type UploadImageResult = {
  url: string;
  filename: string;
  size: number;
};

/** Multipart upload for reference images; returns a same-origin /uploads/... URL. */
export async function uploadAudio(file: File): Promise<UploadImageResult> {
  const body = new FormData();
  body.append("file", file);
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(apiUrl("/api/uploads/audio"), { method: "POST", headers, body });
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

export async function uploadImage(file: File): Promise<UploadImageResult> {
  const body = new FormData();
  body.append("file", file);
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(apiUrl("/api/uploads/images"), { method: "POST", headers, body });
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

export type AgentSkill = { id: string; name: string; description: string };
export type AgentUiMsg = { id: number; role: "user" | "assistant"; content: string };
export type AgentConfirm = {
  node_id: string;
  node_type: string;
  label: string;
  model_id: string;
  estimated_cost: number;
  unit?: string;
};
export type AgentSessionOut = {
  workflow_id: number;
  skill_id: string;
  status: string;
  model_id: string;
  pending_confirm: AgentConfirm | null;
  messages: AgentUiMsg[];
};
export type AgentGraph = { nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>> };
export type AgentViewport = { x: number; y: number };

export type AgentStreamHandlers = {
  onToken?: (text: string) => void;
  onTool?: (ev: { name: string; status: string; detail: string }) => void;
  onGraph?: (graph: AgentGraph) => void;
  onConfirm?: (c: AgentConfirm) => void;
  onError?: (detail: string) => void;
  onDone?: (status: string) => void;
};

async function readAgentSse(path: string, body: unknown, handlers: AgentStreamHandlers, signal?: AbortSignal) {
  const token = getToken();
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : "Agent 请求失败");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const chunks = buf.split("\n\n");
    buf = chunks.pop() || "";
    for (const chunk of chunks) {
      const lines = chunk.split("\n");
      let event = "message";
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      } catch {
        continue;
      }
      if (event === "token") handlers.onToken?.(String(data.text || ""));
      else if (event === "tool") {
        handlers.onTool?.({
          name: String(data.name || ""),
          status: String(data.status || ""),
          detail: String(data.detail || ""),
        });
      } else if (event === "graph") handlers.onGraph?.(data as AgentGraph);
      else if (event === "confirm_required") handlers.onConfirm?.(data as AgentConfirm);
      else if (event === "error") handlers.onError?.(String(data.detail || "Agent 出错"));
      else if (event === "done") handlers.onDone?.(String(data.status || "idle"));
    }
  }
}

export function streamAgentChat(
  body: {
    workflow_id: number;
    model_id?: string;
    skill_id?: string;
    text: string;
    selected_node_id?: string;
    viewport?: AgentViewport;
  },
  handlers: AgentStreamHandlers,
  signal?: AbortSignal,
) {
  return readAgentSse("/api/agent/chat", body, handlers, signal);
}

export function streamAgentResume(
  body: {
    workflow_id: number;
    accept: boolean;
    selected_node_id?: string;
    viewport?: AgentViewport;
  },
  handlers: AgentStreamHandlers,
  signal?: AbortSignal,
) {
  return readAgentSse("/api/agent/resume", body, handlers, signal);
}
