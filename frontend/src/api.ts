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
  kind?: string;
  project?: Record<string, unknown>;
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
      const fresh = await api<WorkflowRun>(`/api/workflows/runs/${runId}`);
      await onUpdate(fresh);
      if (isTerminalRun(fresh.status)) {
        stop();
        return;
      }
      await sleep(POLL_INTERVAL_MS, ctrl.signal);
    }
  };

  void (async () => {
    const token = getToken();
    try {
      const res = await fetch(`/api/workflows/runs/${runId}/events`, {
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
  const res = await fetch("/api/uploads/videos", { method: "POST", headers, body });
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
