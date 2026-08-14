import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, type AdminUser, type BalanceEntry, type Channel, type ChannelProbe } from "../api";
import { useAuth } from "../auth";
import LedgerModal from "../components/LedgerModal";

type ChannelForm = {
  name: string;
  provider: string;
  kind: string;
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
    kind: "video",
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
    kind: "video",
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
    kind: "video",
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
    kind: "video",
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
    kind: "video",
    base_url: "https://api.agnes-ai.cn",
    model_id: "agnes-pavo",
    upstream_model: "agnes-video-v2.0",
    cost_per_second: 0,
    priority: 10,
    enabled: false,
    remark: "免费渠道，超管改 Key 后启用",
  },
  "llm-sim": {
    label: "本地 LLM 模拟",
    hint: "不调上游，即时返回 Brief / 单镜 JSON。kind=llm",
    provider: "mock",
    kind: "llm",
    base_url: "",
    model_id: "llm-local-simulate",
    upstream_model: "local-simulate",
    cost_per_second: 0,
    priority: 95,
    enabled: true,
    remark: "本地即时文案。真模型请另启用 OpenAI / Anthropic 并填 Key。",
  },
  "openai-llm": {
    label: "OpenAI 兼容 · 对话",
    hint: "Chat Completions。base_url 可改成网关；Bearer token。kind=llm",
    provider: "openai",
    kind: "llm",
    base_url: "https://api.openai.com/v1",
    model_id: "gpt-4o-mini",
    upstream_model: "gpt-4o-mini",
    cost_per_second: 0,
    priority: 60,
    enabled: false,
    remark: "超管改 Key 后启用。自定义网关请改 base_url。",
  },
  anthropic: {
    label: "Anthropic · 对话",
    hint: "Messages API，鉴权头 x-api-key。kind=llm",
    provider: "anthropic",
    kind: "llm",
    base_url: "https://api.anthropic.com",
    model_id: "claude-sonnet-4-5",
    upstream_model: "claude-sonnet-4-5",
    cost_per_second: 0,
    priority: 50,
    enabled: false,
    remark: "超管改 Key 后启用。",
  },
  "openai-custom": {
    label: "自定义 token（OpenAI 兼容）",
    hint: "任意 base_url + Bearer。One API / New API 等网关。kind=llm",
    provider: "openai",
    kind: "llm",
    base_url: "https://api.example.com/v1",
    model_id: "gpt-4o-mini",
    upstream_model: "gpt-4o-mini",
    cost_per_second: 0,
    priority: 55,
    enabled: false,
    remark: "自填 base_url 与模型 ID。",
  },
  "edge-tts": {
    label: "Edge TTS（aisrv）",
    hint: "本机 openai-edge-tts 容器。默认钥匙来自 AISRV_API_KEY。kind=tts",
    provider: "openai",
    kind: "tts",
    base_url: "http://127.0.0.1:5050",
    model_id: "tts-1",
    upstream_model: "tts-1",
    cost_per_second: 0,
    priority: 90,
    enabled: true,
    remark: "compose 服务名 aisrv；Docker 内 base_url 用 http://aisrv:5050。",
  },
  "t2i-sim": {
    label: "本地文生图模拟",
    hint: "占位图，不接真模型，不扣费。kind=image",
    provider: "mock",
    kind: "image",
    base_url: "",
    model_id: "t2i-local-simulate",
    upstream_model: "local-simulate",
    cost_per_second: 0,
    priority: 95,
    enabled: true,
    remark: "本轮只出占位图。",
  },
};

const KIND_LABEL: Record<string, string> = {
  video: "视频",
  llm: "LLM",
  tts: "TTS",
  image: "文生图",
};

function guessPreset(ch: Pick<Channel, "provider" | "kind" | "model_id" | "base_url">): string {
  const kind = ch.kind || "video";
  if (kind === "image") return "t2i-sim";
  if (kind === "tts") return "edge-tts";
  if (kind === "llm" && ch.provider === "mock") return "llm-sim";
  if (ch.provider === "anthropic") return "anthropic";
  if (ch.provider === "openai" && kind === "llm") {
    return (ch.base_url || "").includes("openai.com") ? "openai-llm" : "openai-custom";
  }
  if (ch.provider === "agnes" || ch.provider === "pavo") return "agnes";
  if (ch.provider === "mock") return "mock";
  if (ch.model_id === "seedance-2.5") return "ark-2.5";
  if (ch.model_id === "seedance-lite") return "ark-lite";
  if (ch.provider === "ark" || ch.provider === "fal" || ch.provider === "volc") return "ark";
  return "ark-lite";
}

const emptyChannel: ChannelForm = {
  name: "",
  provider: "ark",
  kind: "video",
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
  const [createOpen, setCreateOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingKeyHint, setEditingKeyHint] = useState("");
  const [formError, setFormError] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [balanceEditId, setBalanceEditId] = useState<number | null>(null);
  const [balanceDraft, setBalanceDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [probingId, setProbingId] = useState<number | null>(null);
  const [probes, setProbes] = useState<Record<number, ChannelProbe>>({});
  const [pendingDelete, setPendingDelete] = useState<Channel | null>(null);
  const [deleting, setDeleting] = useState(false);
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
              : key === "openai-llm"
                ? "OpenAI 兼容 · 对话"
                : key === "anthropic"
                  ? "Anthropic · 对话"
                  : key === "openai-custom"
                    ? "自定义 token（OpenAI 兼容）"
                    : key === "edge-tts"
                      ? "Edge TTS（aisrv）"
                      : key === "llm-sim"
                        ? "本地 LLM 模拟"
                        : key === "t2i-sim"
                          ? "本地文生图模拟"
                          : form.name;
    setForm((prev) => ({
      ...prev,
      provider: preset.provider || key,
      kind: preset.kind || prev.kind,
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

  function openCreate() {
    setFormError("");
    setEditingId(null);
    setEditingKeyHint("");
    setPresetKey("ark-lite");
    const preset = PROVIDER_PRESETS["ark-lite"];
    setForm({
      ...emptyChannel,
      provider: preset.provider || "ark",
      kind: preset.kind || "video",
      base_url: preset.base_url ?? emptyChannel.base_url,
      model_id: preset.model_id || emptyChannel.model_id,
      upstream_model: preset.upstream_model || emptyChannel.upstream_model,
      cost_per_second: preset.cost_per_second ?? emptyChannel.cost_per_second,
      priority: preset.priority ?? emptyChannel.priority,
      enabled: preset.enabled ?? false,
      remark: preset.remark ?? "",
      api_key: "",
      name: "Seedance Lite（火山方舟）",
    });
    setCreateOpen(true);
  }

  function closeEditor() {
    setCreateOpen(false);
    setEditingId(null);
    setEditingKeyHint("");
    setFormError("");
  }

  function openEdit(ch: Channel) {
    setFormError("");
    setError("");
    setMsg("");
    setEditingId(ch.id);
    setEditingKeyHint(ch.api_key_masked || "未设置");
    setPresetKey(guessPreset(ch));
    setForm({
      name: ch.name,
      provider: ch.provider,
      kind: ch.kind || "video",
      base_url: ch.base_url || "",
      api_key: "",
      model_id: ch.model_id,
      upstream_model: ch.upstream_model,
      cost_per_second: ch.cost_per_second,
      priority: ch.priority,
      enabled: ch.enabled,
      remark: ch.remark || "",
    });
    setCreateOpen(true);
  }

  async function onSaveChannel(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    setError("");
    setMsg("");
    const payload: Record<string, unknown> = { ...form };
    if (editingId != null && !String(form.api_key || "").trim()) {
      delete payload.api_key;
    }
    try {
      if (editingId != null) {
        await api(`/api/admin/channels/${editingId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        const key = String(form.api_key || "").trim();
        const isArkVideo =
          (form.kind || "video") === "video" &&
          (form.provider === "ark" || form.provider === "fal" || form.provider === "volc");
        if (key && isArkVideo) {
          const siblings = channels.filter(
            (c) =>
              c.id !== editingId &&
              (c.kind || "video") === "video" &&
              (c.provider === "ark" || c.provider === "fal" || c.provider === "volc"),
          );
          for (const target of siblings) {
            await api(`/api/admin/channels/${target.id}`, {
              method: "PATCH",
              body: JSON.stringify({ api_key: key }),
            });
          }
        }
        setMsg("渠道已更新");
      } else {
        await api("/api/admin/channels", { method: "POST", body: JSON.stringify(form) });
        setMsg("渠道已添加");
      }
      setForm(emptyChannel);
      closeEditor();
      await reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : editingId != null ? "保存失败" : "添加失败");
    }
  }

  function askDelete(ch: Channel) {
    setError("");
    setMsg("");
    setPendingDelete(ch);
  }

  async function confirmDelete() {
    const ch = pendingDelete;
    if (!ch) return;
    setDeleting(true);
    setError("");
    setMsg("");
    try {
      await api(`/api/admin/channels/${ch.id}`, { method: "DELETE" });
      setProbes((prev) => {
        const next = { ...prev };
        delete next[ch.id];
        return next;
      });
      if (editingId === ch.id) closeEditor();
      setPendingDelete(null);
      setMsg(`已删除「${ch.name}」`);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  }

  async function probeChannel(ch: Channel) {
    setError("");
    setMsg("");
    setProbingId(ch.id);
    try {
      const out = await api<ChannelProbe>(`/api/admin/channels/${ch.id}/probe`, { method: "POST" });
      setProbes((prev) => ({ ...prev, [ch.id]: out }));
      setMsg(out.ok ? `${ch.name}：${out.message}` : "");
      if (!out.ok) setError(`${ch.name} 探活失败：${out.message}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "探活失败");
    } finally {
      setProbingId(null);
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
          管理上游渠道：视频（Seedance / Agnes）、LLM（本地模拟 / OpenAI / Anthropic）、TTS（aisrv）。
          Key 只存在渠道表。本地 LLM / 文生图模拟与 TTS 本轮不扣费。
        </p>
      </div>

      {(error || msg) && (
        <div className="admin-banner">
          {error && <p className="error">{error}</p>}
          {msg && <p className="ok">{msg}</p>}
        </div>
      )}

      <div className="admin-grid">
        <div className="panel wide">
          <div className="admin-panel-head">
            <div>
              <h2>渠道列表</h2>
              <p className="muted">
                点「编辑」可改全部设置。Key 只存在渠道表；编辑时 Key 留空则不改。Seedance Lite / 2.5 改 Key 会同步。
              </p>
            </div>
            <button type="button" className="primary admin-cta" onClick={openCreate}>
              新增渠道
            </button>
          </div>
          <div className="admin-list">
            {channels.map((ch) => (
              <div className="admin-row" key={ch.id}>
                <div className="admin-row-main">
                  <div className="admin-row-title">
                    <strong>{ch.name}</strong>
                    <span className="admin-chip">{KIND_LABEL[ch.kind || "video"] || ch.kind}</span>
                    {ch.provider === "agnes" || ch.provider === "pavo" ? (
                      <span className="admin-chip">免费</span>
                    ) : null}
                    {ch.provider === "ark" || ch.provider === "fal" || ch.provider === "volc" ? (
                      <span className="admin-chip">方舟</span>
                    ) : null}
                    <span className={`admin-chip ${ch.enabled ? "is-on" : "is-off"}`}>
                      {ch.enabled ? "已启用" : "已停用"}
                    </span>
                  </div>
                  <div className="admin-row-meta">
                    <span>{ch.model_id}</span>
                    <span>{ch.provider}</span>
                    <span>Key {ch.api_key_masked}</span>
                    <span>优先级 {ch.priority}</span>
                    <span>{ch.cost_per_second}/秒</span>
                  </div>
                  {ch.remark && <p className="admin-row-note">{ch.remark}</p>}
                  {probes[ch.id] && (
                    <p className={`admin-row-note ${probes[ch.id].ok ? "is-ok" : "is-err"}`}>
                      {probes[ch.id].ok ? "探活成功" : "探活失败"} · {probes[ch.id].message}
                      {probes[ch.id].latency_ms != null ? ` · ${probes[ch.id].latency_ms}ms` : ""}
                    </p>
                  )}
                </div>
                <div className="admin-actions">
                  <button
                    type="button"
                    className="admin-btn"
                    disabled={probingId === ch.id}
                    onClick={() => void probeChannel(ch)}
                  >
                    {probingId === ch.id ? "探活中" : "探活"}
                  </button>
                  <button type="button" className="admin-btn" onClick={() => openEdit(ch)}>
                    编辑
                  </button>
                  <button
                    type="button"
                    className="admin-btn"
                    onClick={() => void toggle(ch)}
                  >
                    {ch.enabled ? "停用" : "启用"}
                  </button>
                  <button
                    type="button"
                    className="admin-btn admin-btn-danger"
                    onClick={() => askDelete(ch)}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel wide">
          <div className="admin-panel-head">
            <div>
              <h2>用户余额</h2>
              <p className="muted">改余额立即生效；流水按每次变动一行记录。</p>
            </div>
          </div>
          <div className="table admin-table">
            <div className="row head">
              <span>邮箱</span>
              <span>角色</span>
              <span>余额</span>
              <span>操作</span>
            </div>
            {users.map((u) => (
              <div className="row" key={u.id}>
                <span>{u.email}</span>
                <span className="muted">{u.role === "super_admin" ? "超管" : "用户"}</span>
                <span className="admin-balance">{u.balance.toFixed(2)}</span>
                <span className="admin-table-ops">
                  {balanceEditId === u.id ? (
                    <div className="admin-inline compact">
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={balanceDraft}
                        onChange={(e) => setBalanceDraft(e.target.value)}
                        autoFocus
                      />
                      <div className="admin-actions">
                        <button
                          type="button"
                          className="admin-btn"
                          disabled={busy}
                          onClick={() => setBalanceEditId(null)}
                        >
                          取消
                        </button>
                        <button
                          type="button"
                          className="admin-btn admin-btn-fill"
                          disabled={busy}
                          onClick={() => void saveBalance(u)}
                        >
                          保存
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="admin-actions">
                      <button type="button" className="admin-btn" onClick={() => openBalanceEdit(u)}>
                        改余额
                      </button>
                      <button type="button" className="admin-btn" onClick={() => void openLedger(u)}>
                        流水
                      </button>
                    </div>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
      {createOpen && (
        <div className="modal-back" onClick={closeEditor} role="presentation">
          <form
            className="modal channel-create-modal"
            onClick={(e) => e.stopPropagation()}
            onSubmit={onSaveChannel}
          >
            <div className="channel-create-head">
              <h2>{editingId != null ? "编辑渠道" : "新增渠道"}</h2>
              <button type="button" className="admin-btn" onClick={closeEditor}>
                返回
              </button>
            </div>
            {formError && <p className="error">{formError}</p>}
            <label>
              渠道类型预设
              <select value={presetKey} onChange={(e) => applyPreset(e.target.value)}>
                {Object.entries(PROVIDER_PRESETS).map(([key, p]) => (
                  <option key={key} value={key}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            {presetHint && (
              <p className="muted" style={{ marginTop: "-0.35rem" }}>
                {presetHint}
              </p>
            )}
            {(
              [
                ["name", "名称"],
                ["provider", "provider（ark / openai / anthropic / mock / agnes）"],
                ["kind", "kind（video / llm / tts / image）"],
                ["base_url", "Base URL"],
                ["api_key", "API Key"],
                ["model_id", "对外模型 ID"],
                ["upstream_model", "上游模型或推理接入点 ID（ep-xxx）"],
                ["remark", "备注"],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  type={key === "api_key" ? "password" : "text"}
                  autoComplete={key === "api_key" ? "off" : undefined}
                  value={String(form[key])}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                  required={key !== "remark" && key !== "base_url" && !(key === "api_key" && editingId != null)}
                  placeholder={
                    key === "api_key" && editingId != null
                      ? `留空则不改（当前 ${editingKeyHint}）`
                      : undefined
                  }
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
            <p className="muted" style={{ marginTop: "-0.35rem" }}>
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
            <p className="muted" style={{ marginTop: "-0.35rem" }}>
              数字越大越优先出现在模型列表。建议：方舟 Lite 80、2.5 70、本地模拟 40、Pavo 10。
            </p>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              />
              启用（建议先写入真实 Key 再勾选）
            </label>
            <div className="modal-actions">
              <button type="submit" className="primary admin-cta">
                {editingId != null ? "保存修改" : "保存渠道"}
              </button>
            </div>
          </form>
        </div>
      )}
      {pendingDelete && (
        <div
          className="modal-back"
          onClick={() => !deleting && setPendingDelete(null)}
          role="presentation"
        >
          <div
            className="modal admin-confirm-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <h2>确认删除</h2>
            <p>
              确定删除渠道「<strong>{pendingDelete.name}</strong>」？此操作不可撤销。
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="admin-btn"
                disabled={deleting}
                onClick={() => setPendingDelete(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="admin-btn danger-solid"
                disabled={deleting}
                onClick={() => void confirmDelete()}
              >
                {deleting ? "删除中…" : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}
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
