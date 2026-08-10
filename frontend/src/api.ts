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
