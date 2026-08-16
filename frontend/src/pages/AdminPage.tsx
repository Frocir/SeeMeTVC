import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { api, type AdminUser, type BalanceEntry, type Channel, type ChannelProbe } from "../api";
import { useAuth } from "../auth";
import LedgerModal from "../components/LedgerModal";
import {
  CLAUDE_SONNET46_MODEL_ID,
  DEEPSEEK_BASE,
  DEEPSEEK_HOST,
  DEEPSEEK_TQX_MODEL_ID,
  DEEPSEEK_TQX_UPSTREAM,
  DEEPSEEK_UPSTREAM,
  DEFAULT_AGENT_MODEL_ID,
  GPT54_MODEL_ID,
  TQX_LLM_BASE,
  isOfficialDeepseekUrl,
  isTqxLlmUrl,
} from "../llmIds";

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
  capabilities_json: string;
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
    priority: 90,
    enabled: false,
    remark: "火山方舟 Seedance 2.x（产品称 2.5）。超管改 Key 后启用。",
  },
  "ark-fast": {
    label: "火山方舟 · Seedance Fast",
    hint: "ARK_API_KEY 存渠道表；默认同步音频；约 4–15s；720p。比 2.5 快、比 Lite 有声",
    provider: "ark",
    kind: "video",
    base_url: "https://ark.cn-beijing.volces.com",
    model_id: "seedance-fast",
    upstream_model: "doubao-seedance-2-0-fast-260128",
    cost_per_second: 4,
    priority: 90,
    enabled: false,
    remark: "火山方舟 Seedance 2.0 Fast。超管改 Key 后启用。",
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
  "tqx-claude": {
    label: "Claude Sonnet 4.6",
    hint: "tqx Anthropic Messages。kind=llm",
    provider: "anthropic",
    kind: "llm",
    base_url: TQX_LLM_BASE,
    model_id: CLAUDE_SONNET46_MODEL_ID,
    upstream_model: CLAUDE_SONNET46_MODEL_ID,
    cost_per_second: 0,
    priority: 80,
    enabled: true,
    remark: `tqx Anthropic Messages。模型 ${CLAUDE_SONNET46_MODEL_ID}。`,
  },
  "tqx-g54": {
    label: "GPT-5.4",
    hint: `tqx OpenAI 兼容。显示 GPT-5.4，上游 ${GPT54_MODEL_ID}。kind=llm`,
    provider: "openai",
    kind: "llm",
    base_url: TQX_LLM_BASE,
    model_id: GPT54_MODEL_ID,
    upstream_model: GPT54_MODEL_ID,
    cost_per_second: 0,
    priority: 70,
    enabled: true,
    remark: `tqx OpenAI 兼容。显示 GPT-5.4，上游 ${GPT54_MODEL_ID}。`,
  },
  "deepseek-v4": {
    label: DEFAULT_AGENT_MODEL_ID,
    hint: "官方 DeepSeek Chat Completions。kind=llm",
    provider: "openai",
    kind: "llm",
    base_url: DEEPSEEK_BASE,
    model_id: DEFAULT_AGENT_MODEL_ID,
    upstream_model: DEEPSEEK_UPSTREAM,
    cost_per_second: 0,
    priority: 90,
    enabled: true,
    remark: `官方 DeepSeek。Base URL: ${DEEPSEEK_BASE} ；上游模型 ${DEEPSEEK_UPSTREAM}。`,
  },
  "tqx-dsv4": {
    label: "DeepSeek-V4-Pro（tqx）",
    hint: "tqx 中转。与官方 DeepSeek 分开，Key 不能混用。kind=llm",
    provider: "openai",
    kind: "llm",
    base_url: TQX_LLM_BASE,
    model_id: DEEPSEEK_TQX_MODEL_ID,
    upstream_model: DEEPSEEK_TQX_UPSTREAM,
    cost_per_second: 0,
    priority: 85,
    enabled: true,
    remark: `tqx 中转 DeepSeek。上游 ${DEEPSEEK_TQX_UPSTREAM}。不要填官方 ${DEEPSEEK_HOST} 的 Key。`,
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
  "openai-image": {
    label: "OpenAI 兼容 · 图像",
    hint: "Images API：/v1/images/generations。kind=image",
    provider: "openai",
    kind: "image",
    base_url: "https://api.openai.com/v1",
    model_id: "gpt-image-1",
    upstream_model: "gpt-image-1",
    cost_per_second: 0,
    priority: 70,
    enabled: false,
    remark: "超管填 Key 后启用。image 渠道按单张图片扣费。",
  },
  "gemini-image": {
    label: "向量引擎 · Gemini 文生图",
    hint: "Gemini 原生 generateContent。Bearer sk-… ；模型如 gemini-2.5-flash-image",
    provider: "gemini",
    kind: "image",
    base_url: "https://api.vectorengine.ai",
    model_id: "gemini-2.5-flash-image",
    upstream_model: "gemini-2.5-flash-image",
    cost_per_second: 0,
    priority: 90,
    enabled: false,
    remark: "向量引擎 Gemini 文生图。超管改 Key 后启用。",
  },
  "openai-asr": {
    label: "OpenAI 兼容 · 语音识别",
    hint: "Whisper / 网关 /v1/audio/transcriptions。kind=asr",
    provider: "openai",
    kind: "asr",
    base_url: "https://api.openai.com/v1",
    model_id: "whisper-1",
    upstream_model: "whisper-1",
    cost_per_second: 0,
    priority: 70,
    enabled: false,
    remark: "超管填 Key 后启用。",
  },
};

const KIND_LABEL: Record<string, string> = {
  video: "视频",
  llm: "LLM",
  tts: "TTS",
  image: "文生图",
  asr: "ASR",
};

function guessPreset(ch: Pick<Channel, "provider" | "kind" | "model_id" | "base_url">): string {
  const kind = ch.kind || "video";
  if (kind === "image") {
    const mid = (ch.model_id || "").toLowerCase();
    if (
      ch.provider === "gemini" ||
      ch.provider === "vectorengine" ||
      ch.provider === "google" ||
      mid.includes("gemini")
    ) {
      return "gemini-image";
    }
    return "openai-image";
  }
  if (kind === "asr") return "openai-asr";
  if (kind === "tts") return "edge-tts";
  if (isTqxLlmUrl(ch.base_url || "")) {
    if (ch.model_id === GPT54_MODEL_ID || ch.model_id === "g5.5") return "tqx-g54";
    if ((ch.model_id || "").toLowerCase().includes("deepseek")) return "tqx-dsv4";
    return "tqx-claude";
  }
  if (isOfficialDeepseekUrl(ch.base_url || "") || ch.model_id === DEFAULT_AGENT_MODEL_ID) {
    return "deepseek-v4";
  }
  if (ch.provider === "anthropic") return "anthropic";
  if (ch.provider === "openai" && kind === "llm") {
    return (ch.base_url || "").includes("openai.com") ? "openai-llm" : "openai-custom";
  }
  if (ch.provider === "agnes" || ch.provider === "pavo") return "agnes";
  if (ch.model_id === "seedance-2.5") return "ark-2.5";
  if (ch.model_id === "seedance-fast") return "ark-fast";
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
  capabilities_json: "",
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
    const defaultName = preset.label || form.name;
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
      capabilities_json: JSON.stringify((ch.config_json as { capabilities?: unknown } | undefined)?.capabilities || {}, null, 2),
    });
    setCreateOpen(true);
  }

  async function onSaveChannel(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    setError("");
    setMsg("");
    const { capabilities_json, ...rest } = form;
    const payload: Record<string, unknown> = { ...rest };
    const rawCaps = (capabilities_json || "").trim();
    if (rawCaps && rawCaps !== "{}") {
      try {
        const parsed = JSON.parse(rawCaps) as unknown;
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setFormError("能力覆盖必须是 JSON 对象，例如 {\"supports_first_last_frame\": true}");
          return;
        }
        payload.config_json = { capabilities: parsed };
      } catch {
        setFormError("能力覆盖 JSON 无法解析");
        return;
      }
    } else {
      payload.config_json = {};
    }
    delete payload.capabilities_json;
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
          管理上游渠道：视频（Seedance / Agnes）、LLM（OpenAI / Anthropic）、TTS（aisrv）、文生图、ASR。
          Key 只存在渠道表。请填写真实钥匙后再启用。
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
                点「编辑」可改全部设置。Key 只存在渠道表；编辑时 Key 留空则不改。Seedance Lite / Fast / 2.5 改 Key 会同步。
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
                    <span>{ch.cost_per_second}{ch.kind === "image" ? "/张" : ch.kind === "asr" ? "/次" : "/秒"}</span>
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
                ["provider", "provider（ark / openai / anthropic / agnes / gemini）"],
                ["kind", "kind（video / llm / tts / image / asr）"],
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
              {form.kind === "image"
                ? "每张图片消耗余额"
                : form.kind === "asr"
                  ? "每次转写消耗余额"
                  : "每秒消耗余额（Agnes 免费可为 0）"}
              <input
                type="number"
                step="0.01"
                min={0}
                value={form.cost_per_second}
                onChange={(e) => setForm({ ...form, cost_per_second: Number(e.target.value) })}
              />
            </label>
            <p className="muted" style={{ marginTop: "-0.35rem" }}>
              {form.kind === "image"
                ? "image 渠道按单张图片扣费；TextToImage 生成时直接扣。"
                : form.kind === "asr"
                  ? "asr 渠道本轮默认不扣费。填写真实 Key 后启用即可转写。"
                  : "用户侧按「秒 × 此单价」扣费；请与上游真实成本大致对齐。"}
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
              数字越大越优先出现在模型列表。建议：方舟 2.5 90、Lite 80、Pavo 10。
            </p>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              />
              启用（建议先写入真实 Key 再勾选）
            </label>
            <label>
              能力覆盖 JSON（可选）
              <textarea
                rows={5}
                value={form.capabilities_json}
                onChange={(e) => setForm({ ...form, capabilities_json: e.target.value })}
                placeholder='{"supports_first_last_frame": true}'
              />
            </label>
            <p className="muted" style={{ marginTop: "-0.35rem" }}>
              覆盖 provider 默认能力。留空则用内置矩阵（如 Seedance 2.5 / Fast 支持首尾帧，Lite / OpenAI 图默认仅 size）。
            </p>
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
