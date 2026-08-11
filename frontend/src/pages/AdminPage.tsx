import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, type AdminUser, type Channel } from "../api";
import { useAuth } from "../auth";

type ChannelForm = {
  name: string;
  provider: string;
  base_url: string;
  api_key: string;
  model_id: string;
  upstream_model: string;
  cost_per_second: number;
  priority: number;
  enabled: boolean;
  remark: string;
};

const PROVIDER_PRESETS: Record<
  string,
  Partial<ChannelForm> & { label: string; hint: string }
> = {
  fal: {
    label: "fal (Seedance)",
    hint: "fal queue API，按秒计费",
    provider: "fal",
    base_url: "https://queue.fal.run",
    model_id: "seedance-lite",
    upstream_model: "fal-ai/bytedance/seedance/v1/lite/text-to-video",
    cost_per_second: 1,
    enabled: true,
  },
  mock: {
    label: "mock（本地演示）",
    hint: "不调上游，生成本地样片（可 trim/mux）；优先级应高于 Agnes",
    provider: "mock",
    base_url: "",
    model_id: "seedance-lite",
    upstream_model: "mock",
    api_key: "mock:demo",
    cost_per_second: 1,
    priority: 100,
    enabled: true,
  },
  agnes: {
    label: "Agnes AI Pavo（免费）",
    hint: "免费异步视频 API；国内默认 https://api.agnes-ai.cn ；默认关闭，填 Key 后启用",
    provider: "agnes",
    base_url: "https://api.agnes-ai.cn",
    model_id: "agnes-pavo",
    upstream_model: "agnes-video-v2.0",
    cost_per_second: 0,
    priority: 10,
    enabled: false,
    remark: "免费渠道，超管启用后全站可用；优先级低于 mock，避免抢默认模型",
  },
};

const emptyChannel: ChannelForm = {
  name: "",
  provider: "fal",
  base_url: "https://queue.fal.run",
  api_key: "",
  model_id: "seedance-lite",
  upstream_model: "fal-ai/bytedance/seedance/v1/lite/text-to-video",
  cost_per_second: 1,
  priority: 10,
  enabled: true,
  remark: "",
};

export default function AdminPage() {
  const { me, refresh } = useAuth();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [form, setForm] = useState(emptyChannel);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [keyEditId, setKeyEditId] = useState<number | null>(null);
  const [keyDraft, setKeyDraft] = useState("");
  const [balanceEditId, setBalanceEditId] = useState<number | null>(null);
  const [balanceDraft, setBalanceDraft] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    const [chs, us] = await Promise.all([
      api<Channel[]>("/api/admin/channels"),
      api<AdminUser[]>("/api/admin/users"),
    ]);
    setChannels(chs);
    setUsers(us);
  }

  useEffect(() => {
    if (me?.role === "super_admin") void reload().catch((e) => setError(String(e.message || e)));
  }, [me]);

  if (me?.role !== "super_admin") return <Navigate to="/" replace />;

  function applyPreset(provider: string) {
    const preset = PROVIDER_PRESETS[provider];
    if (!preset) {
      setForm({ ...form, provider });
      return;
    }
    setForm((prev) => ({
      ...prev,
      provider: preset.provider || provider,
      base_url: preset.base_url ?? prev.base_url,
      model_id: preset.model_id || prev.model_id,
      upstream_model: preset.upstream_model || prev.upstream_model,
      cost_per_second: preset.cost_per_second ?? prev.cost_per_second,
      priority: preset.priority ?? prev.priority,
      enabled: preset.enabled ?? prev.enabled,
      remark: preset.remark ?? prev.remark,
      api_key: preset.api_key ?? prev.api_key,
      name: prev.name || (provider === "agnes" ? "Agnes AI Pavo (free)" : prev.name),
    }));
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      await api("/api/admin/channels", { method: "POST", body: JSON.stringify(form) });
      setForm(emptyChannel);
      setMsg("渠道已添加");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "失败");
    }
  }

  async function toggle(ch: Channel) {
    setError("");
    try {
      await api(`/api/admin/channels/${ch.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !ch.enabled }),
      });
      setMsg(`${ch.name} 已${ch.enabled ? "停用" : "启用"}`);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "启停失败");
    }
  }

  function openKeyEdit(ch: Channel) {
    setKeyEditId(ch.id);
    setKeyDraft("");
    setBalanceEditId(null);
    setError("");
    setMsg("");
  }

  async function saveKey(ch: Channel) {
    if (!keyDraft.trim()) {
      setError("请输入新的 API Key");
      return;
    }
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api(`/api/admin/channels/${ch.id}`, {
        method: "PATCH",
        body: JSON.stringify({ api_key: keyDraft.trim() }),
      });
      setMsg(`${ch.name} 的 Key 已更新`);
      setKeyEditId(null);
      setKeyDraft("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新 Key 失败");
    } finally {
      setBusy(false);
    }
  }

  function openBalanceEdit(u: AdminUser) {
    setBalanceEditId(u.id);
    setBalanceDraft(String(u.balance));
    setKeyEditId(null);
    setError("");
    setMsg("");
  }

  async function saveBalance(u: AdminUser) {
    const next = Number(balanceDraft);
    if (!Number.isFinite(next) || next < 0) {
      setError("余额须为 ≥ 0 的数字");
      return;
    }
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api(`/api/admin/users/${u.id}/balance`, {
        method: "PATCH",
        body: JSON.stringify({ balance: next }),
      });
      setMsg(`${u.email} 余额已设为 ${next.toFixed(2)}`);
      setBalanceEditId(null);
      await reload();
      if (u.id === me?.id) await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "改余额失败");
    } finally {
      setBusy(false);
    }
  }

  const presetHint = PROVIDER_PRESETS[form.provider]?.hint;

  return (
    <section className="admin">
      <div className="page-head">
        <p className="eyebrow">超管</p>
        <h1>超管后台管理</h1>
        <p className="lead">
          管理上游渠道（含免费 Agnes AI Pavo）。Pavo 默认关闭，填入 API Key 并启用后全站可选用。
        </p>
      </div>

      {(error || msg) && (
        <div className="admin-banner">
          {error && <p className="error">{error}</p>}
          {msg && <p className="ok">{msg}</p>}
        </div>
      )}

      <div className="admin-grid">
        <form className="panel" onSubmit={onCreate}>
          <h2>新增渠道</h2>

          <label>
            渠道类型预设
            <select
              value={PROVIDER_PRESETS[form.provider] ? form.provider : "fal"}
              onChange={(e) => applyPreset(e.target.value)}
            >
              {Object.entries(PROVIDER_PRESETS).map(([key, p]) => (
                <option key={key} value={key}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          {presetHint && (
            <p className="muted" style={{ marginTop: "-0.5rem" }}>
              {presetHint}
            </p>
          )}

          {(
            [
              ["name", "名称"],
              ["provider", "provider（fal / mock / agnes）"],
              ["base_url", "Base URL"],
              ["api_key", "API Key"],
              ["model_id", "对外模型 ID"],
              ["upstream_model", "上游模型（Agnes 填 agnes-video-v2.0）"],
              ["remark", "备注"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                value={String(form[key])}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                required={key !== "remark" && key !== "base_url"}
              />
            </label>
          ))}
          <label>
            每秒消耗余额（Agnes 免费可为 0）
            <input
              type="number"
              step="0.01"
              value={form.cost_per_second}
              onChange={(e) => setForm({ ...form, cost_per_second: Number(e.target.value) })}
            />
          </label>
          <label>
            优先级
            <input
              type="number"
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
            启用（Agnes Pavo 建议填好 Key 后再勾选）
          </label>
          <button type="submit" className="block primary">
            保存渠道
          </button>
        </form>

        <div className="panel">
          <h2>渠道列表</h2>
          {channels.map((ch) => (
            <div className="channel-item" key={ch.id}>
              <div>
                <strong>
                  {ch.name}
                  {ch.provider === "agnes" || ch.provider === "pavo" ? (
                    <span className="status status-succeeded" style={{ marginLeft: "0.5rem" }}>
                      免费
                    </span>
                  ) : null}
                </strong>
                <div className="muted">
                  {ch.model_id} · {ch.provider} · Key {ch.api_key_masked}
                </div>
                <div className="muted">
                  {ch.cost_per_second}/秒 · 优先级 {ch.priority} · {ch.enabled ? "已启用" : "已停用"}
                </div>
                {ch.remark && <div className="muted">{ch.remark}</div>}

                {keyEditId === ch.id && (
                  <div className="inline-edit">
                    <label>
                      新 API Key
                      <input
                        type="password"
                        autoComplete="off"
                        value={keyDraft}
                        onChange={(e) => setKeyDraft(e.target.value)}
                        placeholder="粘贴完整 Key"
                        autoFocus
                      />
                    </label>
                    <div className="inline-edit-actions">
                      <button
                        type="button"
                        className="primary"
                        disabled={busy}
                        onClick={() => void saveKey(ch)}
                      >
                        保存 Key
                      </button>
                      <button
                        type="button"
                        className="ghost"
                        disabled={busy}
                        onClick={() => {
                          setKeyEditId(null);
                          setKeyDraft("");
                        }}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )}
              </div>
              <div className="channel-actions">
                <button type="button" className="ghost" onClick={() => openKeyEdit(ch)}>
                  改 Key
                </button>
                <button type="button" className="ghost" onClick={() => void toggle(ch)}>
                  {ch.enabled ? "停用" : "启用"}
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="panel wide">
          <h2>用户余额</h2>
          <div className="table">
            <div className="row head">
              <span>邮箱</span>
              <span>角色</span>
              <span>余额</span>
              <span>操作</span>
            </div>
            {users.map((u) => (
              <div className="row" key={u.id}>
                <span>{u.email}</span>
                <span>{u.role}</span>
                <span>{u.balance.toFixed(2)}</span>
                <span>
                  {balanceEditId === u.id ? (
                    <div className="inline-edit compact">
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={balanceDraft}
                        onChange={(e) => setBalanceDraft(e.target.value)}
                        autoFocus
                      />
                      <div className="inline-edit-actions">
                        <button
                          type="button"
                          className="primary"
                          disabled={busy}
                          onClick={() => void saveBalance(u)}
                        >
                          保存
                        </button>
                        <button
                          type="button"
                          className="ghost"
                          disabled={busy}
                          onClick={() => setBalanceEditId(null)}
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button type="button" className="ghost" onClick={() => openBalanceEdit(u)}>
                      改余额
                    </button>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
