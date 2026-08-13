import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, type AdminUser, type BalanceEntry, type Channel } from "../api";
import { useAuth } from "../auth";
import LedgerModal from "../components/LedgerModal";

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
  "ark-lite": {
    label: "火山方舟 · Seedance Lite",
    hint: "ARK_API_KEY 存渠道表；Bearer 鉴权。文生/图生同一接口；无原生音频；约 2–12s",
    provider: "ark",
    base_url: "https://ark.cn-beijing.volces.com",
    model_id: "seedance-lite",
    upstream_model: "doubao-seedance-1-0-lite-t2v-250428",
    cost_per_second: 1,
    priority: 80,
    enabled: false,
    remark: "火山方舟 Seedance Lite。upstream 可改为控制台推理接入点 ep-xxx。",
  },
  "ark-2.5": {
    label: "火山方舟 · Seedance 2.5",
    hint: "ARK_API_KEY 存渠道表；默认同步音频；约 4–30s。upstream 填 2.x 模型或 ep-xxx",
    provider: "ark",
    base_url: "https://ark.cn-beijing.volces.com",
    model_id: "seedance-2.5",
    upstream_model: "doubao-seedance-2-0-260128",
    cost_per_second: 8,
    priority: 70,
    enabled: false,
    remark: "火山方舟 Seedance 2.x（产品称 2.5）。超管改 Key 后启用。",
  },
  ark: {
    label: "火山方舟（通用）",
    hint: "自定义 upstream_model（模型 ID 或 ep-xxx）",
    provider: "ark",
    base_url: "https://ark.cn-beijing.volces.com",
    model_id: "seedance-lite",
    upstream_model: "doubao-seedance-1-0-lite-t2v-250428",
    cost_per_second: 1,
    priority: 80,
    enabled: false,
  },
  mock: {
    label: "本地seedance模拟版（Seedance LocalSimulate）",
    hint: "不调上游，本机 ffmpeg 彩条样片；不是真 Seedance",
    provider: "mock",
    base_url: "",
    model_id: "seedance-local-simulate",
    upstream_model: "local-simulate",
    cost_per_second: 0,
    priority: 40,
    enabled: true,
    remark: "本地模拟版。真生成请启用火山方舟 Lite / 2.5。",
  },
  agnes: {
    label: "Agnes AI Pavo（免费）",
    hint: "Key 存在渠道表；超管「改 Key」后启用。国内默认 https://api.agnes-ai.cn",
    provider: "agnes",
    base_url: "https://api.agnes-ai.cn",
    model_id: "agnes-pavo",
    upstream_model: "agnes-video-v2.0",
    cost_per_second: 0,
    priority: 10,
    enabled: false,
    remark: "免费渠道，超管改 Key 后启用",
  },
};

const emptyChannel: ChannelForm = {
  name: "",
  provider: "ark",
  base_url: "https://ark.cn-beijing.volces.com",
  api_key: "",
  model_id: "seedance-lite",
  upstream_model: "doubao-seedance-1-0-lite-t2v-250428",
  cost_per_second: 1,
  priority: 80,
  enabled: false,
  remark: "",
};

export default function AdminPage() {
  const { me, refresh } = useAuth();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [form, setForm] = useState(emptyChannel);
  const [presetKey, setPresetKey] = useState("ark-lite");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [keyEditId, setKeyEditId] = useState<number | null>(null);
  const [keyDraft, setKeyDraft] = useState("");
  const [balanceEditId, setBalanceEditId] = useState<number | null>(null);
  const [balanceDraft, setBalanceDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [ledgerUser, setLedgerUser] = useState<AdminUser | null>(null);
  const [ledger, setLedger] = useState<BalanceEntry[] | null>(null);
  const [ledgerError, setLedgerError] = useState("");

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

  function applyPreset(key: string) {
    const preset = PROVIDER_PRESETS[key];
    setPresetKey(key);
    if (!preset) {
      setForm({ ...form, provider: key });
      return;
    }
    const defaultName =
      key === "agnes"
        ? "Agnes AI Pavo (free)"
        : key === "ark-lite"
          ? "Seedance Lite（火山方舟）"
          : key === "ark-2.5"
            ? "Seedance 2.5（火山方舟）"
            : key === "mock"
              ? "本地seedance模拟版（Seedance LocalSimulate）"
              : form.name;
    setForm((prev) => ({
      ...prev,
      provider: preset.provider || key,
      base_url: preset.base_url ?? prev.base_url,
      model_id: preset.model_id || prev.model_id,
      upstream_model: preset.upstream_model || prev.upstream_model,
      cost_per_second: preset.cost_per_second ?? prev.cost_per_second,
      priority: preset.priority ?? prev.priority,
      enabled: preset.enabled ?? prev.enabled,
      remark: preset.remark ?? prev.remark,
      api_key: preset.api_key ?? prev.api_key,
      name: prev.name || defaultName,
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
    const key = keyDraft.trim();
    if (ch.provider === "ark" || ch.provider === "fal" || ch.provider === "volc") {
      if (key.length < 8) {
        setError("ARK_API_KEY 过短，请粘贴方舟控制台完整 Key。");
        return;
      }
    }
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const targets =
        ch.provider === "ark" || ch.provider === "fal" || ch.provider === "volc"
          ? channels.filter((c) => c.provider === "ark" || c.provider === "fal" || c.provider === "volc")
          : [ch];
      for (const target of targets) {
        await api(`/api/admin/channels/${target.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            api_key: key,
            provider: "ark",
            base_url: "https://ark.cn-beijing.volces.com",
          }),
        });
      }
      const synced =
        (ch.provider === "ark" || ch.provider === "fal") && targets.length > 1
          ? `（已同步到 ${targets.length} 个方舟 Seedance 渠道）`
          : "";
      setMsg(`${ch.name} 的 Key 已更新并写入存储${synced}。需要时再点「启用」。`);
      setKeyEditId(null);
      setKeyDraft("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新 Key 失败");
    } finally {
      setBusy(false);
    }
  }

  async function openLedger(u: AdminUser) {
    setLedgerUser(u);
    setLedger(null);
    setLedgerError("");
    try {
      setLedger(await api<BalanceEntry[]>(`/api/admin/users/${u.id}/ledger`));
    } catch (err) {
      setLedgerError(err instanceof Error ? err.message : "加载流水失败");
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

  const presetHint = PROVIDER_PRESETS[presetKey]?.hint;

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
              value={presetKey}
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
              ["provider", "provider（ark / mock / agnes）"],
              ["base_url", "Base URL（方舟默认 https://ark.cn-beijing.volces.com）"],
              ["api_key", "API Key（ARK_API_KEY）"],
              ["model_id", "对外模型 ID"],
              ["upstream_model", "上游模型或推理接入点 ID（ep-xxx）"],
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
              min={0}
              value={form.cost_per_second}
              onChange={(e) => setForm({ ...form, cost_per_second: Number(e.target.value) })}
            />
          </label>
          <p className="muted" style={{ marginTop: "-0.5rem" }}>
            用户侧按「秒 × 此单价」扣费；请与上游真实成本大致对齐。
          </p>
          <label>
            优先级
            <input
              type="number"
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
            />
          </label>
          <p className="muted" style={{ marginTop: "-0.5rem" }}>
            数字越大越优先出现在模型列表（同 model_id 只展示优先级最高且已启用的一条）。建议：方舟 Lite 80、2.5 70、本地模拟 40、Pavo 10。
          </p>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            />
            启用（建议先「改 Key」写入真实 Key 再勾选）
          </label>
          <button type="submit" className="block primary">
            保存渠道
          </button>
        </form>

        <div className="panel">
          <h2>渠道列表</h2>
          <p className="muted" style={{ marginTop: "-0.35rem" }}>
            API Key 只保存在渠道存储里（与 Pavo 相同）：点「改 Key」写入，再「启用」。Seedance Lite / 2.5
            共用同一把火山方舟 ARK_API_KEY，改任一处会同步。
          </p>
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
                  {ch.provider === "ark" || ch.provider === "fal" || ch.provider === "volc" ? (
                    <span className="status status-running" style={{ marginLeft: "0.5rem" }}>
                      方舟
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
                        placeholder={
                          ch.provider === "ark" || ch.provider === "fal" || ch.provider === "volc"
                            ? "粘贴 ARK_API_KEY（将同步到所有 Seedance 方舟渠道）"
                            : "粘贴完整 Key"
                        }
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
                    <>
                    <button type="button" className="ghost" onClick={() => openBalanceEdit(u)}>
                      改余额
                    </button>
                    <button type="button" className="ghost" onClick={() => void openLedger(u)}>
                      流水
                    </button>
                    </>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
      {ledgerUser && (
        <LedgerModal
          title={`${ledgerUser.email} 的流水`}
          unit={me?.balance_unit || "积分"}
          entries={ledger}
          error={ledgerError}
          onClose={() => {
            setLedgerUser(null);
            setLedger(null);
          }}
        />
      )}
    </section>
  );
}
