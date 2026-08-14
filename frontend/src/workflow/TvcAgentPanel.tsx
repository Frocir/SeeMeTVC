import { useEffect, useRef, useState } from "react";
import {
  api,
  streamAgentChat,
  streamAgentResume,
  type AgentConfirm,
  type AgentGraph,
  type AgentSessionOut,
  type AgentSkill,
  type AgentUiMsg,
  type AgentViewport,
  type ModelOption,
} from "../api";

type ToolLine = { name: string; status: string; detail: string };

type Props = {
  workflowId: number | null;
  models: ModelOption[];
  selectedNodeId: string | null;
  viewport: AgentViewport;
  onGraph: (graph: AgentGraph) => void;
  onLocked: (locked: boolean) => void;
  onBeforeSend: () => Promise<void>;
};

export default function TvcAgentPanel({
  workflowId,
  models,
  selectedNodeId,
  viewport,
  onGraph,
  onLocked,
  onBeforeSend,
}: Props) {
  const preferred =
    models.find((m) => m.model_id === "llm-local-simulate")?.model_id || models[0]?.model_id || "";
  const [modelId, setModelId] = useState(preferred);
  const [skills, setSkills] = useState<AgentSkill[]>([]);
  const [skillId, setSkillId] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<AgentUiMsg[]>([]);
  const [streamText, setStreamText] = useState("");
  const [tools, setTools] = useState<ToolLine[]>([]);
  const [confirm, setConfirm] = useState<AgentConfirm | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!modelId && preferred) setModelId(preferred);
  }, [modelId, preferred]);

  useEffect(() => {
    void api<AgentSkill[]>("/api/agent/skills")
      .then(setSkills)
      .catch(() => setSkills([]));
  }, []);

  useEffect(() => {
    if (!workflowId) return;
    void api<AgentSessionOut>(`/api/agent/session?workflow_id=${workflowId}`)
      .then((s) => {
        setMessages(s.messages || []);
        if (s.skill_id) setSkillId(s.skill_id);
        if (s.model_id) setModelId(s.model_id);
        setConfirm(s.pending_confirm);
        onLocked(s.status === "confirm_pending" || s.status === "running");
      })
      .catch(() => undefined);
  }, [workflowId, onLocked]);

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy, streamText, tools, confirm]);

  function resizeArea() {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }

  function bindHandlers() {
    setError("");
    setStreamText("");
    setTools([]);
    return {
      onToken: (t: string) => setStreamText((prev) => prev + t),
      onTool: (ev: ToolLine) => {
        setTools((prev) => {
          const i = prev.findIndex((x) => x.name === ev.name && x.status === "running");
          if (i >= 0) {
            const next = [...prev];
            next[i] = ev;
            return next;
          }
          return [...prev, ev];
        });
      },
      onGraph,
      onConfirm: (c: AgentConfirm) => setConfirm(c),
      onError: (d: string) => setError(d),
      onDone: (status: string) => {
        setStreamText((text) => {
          if (text.trim()) {
            setMessages((ms) => [...ms, { id: Date.now(), role: "assistant", content: text }]);
          }
          return "";
        });
        if (status === "confirm_pending") {
          setBusy(false);
          onLocked(true);
        } else {
          setConfirm(null);
          setBusy(false);
          onLocked(false);
        }
      },
    };
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy || !workflowId) return;
    if (!models.length) {
      setError("没有可用 LLM，请超管启用渠道");
      return;
    }
    setDraft("");
    if (areaRef.current) areaRef.current.style.height = "auto";
    setMessages((ms) => [...ms, { id: Date.now(), role: "user", content: text }]);
    setBusy(true);
    onLocked(true);
    try {
      await onBeforeSend();
      await streamAgentChat(
        {
          workflow_id: workflowId,
          model_id: modelId,
          skill_id: skillId,
          text,
          selected_node_id: selectedNodeId || "",
          viewport,
        },
    bindHandlers(),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送失败");
      setBusy(false);
      onLocked(false);
    } finally {
      areaRef.current?.focus();
    }
  }

  async function resume(accept: boolean) {
    if (!workflowId || busy) return;
    setBusy(true);
    onLocked(true);
    setConfirm(null);
    try {
      await streamAgentResume(
        {
          workflow_id: workflowId,
          accept,
          selected_node_id: selectedNodeId || "",
          viewport,
        },
        bindHandlers(),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "确认失败");
      setBusy(false);
      onLocked(false);
    }
  }

  return (
    <div className="cv-agent">
      <label className="cv-agent-skill">
        Skill
        <select
          value={skillId}
          disabled={busy}
          onChange={(e) => setSkillId(e.target.value)}
          aria-label="Skill"
        >
          <option value="">（不选 Skill）</option>
          {skills.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <div className="cv-agent-thread" ref={threadRef}>
        {messages.map((m, i) => (
          <div key={`${m.role}-${m.id}-${i}`} className={`cv-agent-msg ${m.role}`}>
            <p>{m.content}</p>
          </div>
        ))}
        {tools.map((t, i) => (
          <div key={`tool-${i}`} className="cv-agent-tool">
            {t.name} · {t.status}
            {t.detail ? ` · ${t.detail}` : ""}
          </div>
        ))}
        {(busy || streamText) && (
          <div className={`cv-agent-msg assistant ${streamText ? "" : "pending"}`}>
            <p>{streamText || "正在回复…"}</p>
          </div>
        )}
        {confirm && (
          <div className="cv-agent-confirm">
            <p>
              确认生成 <strong>{confirm.label}</strong>（{confirm.node_type}）
            </p>
            <p className="cv-agent-confirm-meta">
              模型 {confirm.model_id || "—"} · 预估 {confirm.estimated_cost} {confirm.unit || "积分"}
            </p>
            <div className="cv-agent-confirm-actions">
              <button type="button" className="cv-agent-confirm-yes" disabled={busy} onClick={() => void resume(true)}>
                确认
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => void resume(false)}>
                取消
              </button>
            </div>
          </div>
        )}
        {error && <p className="cv-agent-error">{error}</p>}
      </div>
      <form
        className="cv-agent-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <textarea
          ref={areaRef}
          className="cv-agent-input"
          rows={2}
          value={draft}
          disabled={busy || !workflowId}
          placeholder="发给 TVC Agent"
          onChange={(e) => {
            setDraft(e.target.value);
            resizeArea();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <div className="cv-agent-bar">
          <select
            className="cv-agent-model"
            value={modelId}
            disabled={busy || models.length === 0}
            onChange={(e) => setModelId(e.target.value)}
            aria-label="LLM"
          >
            {models.length === 0 && <option value="">无可用 LLM</option>}
            {models.map((opt) => (
              <option key={opt.model_id} value={opt.model_id}>
                {opt.label || opt.model_id}
              </option>
            ))}
          </select>
          <button
            type="submit"
            className="cv-agent-send"
            disabled={busy || !draft.trim() || models.length === 0 || !workflowId}
            aria-label="发送"
            title="发送"
          >
            <svg viewBox="0 0 24 24" aria-hidden>
              <path
                fill="currentColor"
                d="M12 4.2 4.8 11.4l1.4 1.4L11 7.9V20h2V7.9l4.8 4.9 1.4-1.4L12 4.2Z"
              />
            </svg>
          </button>
        </div>
      </form>
    </div>
  );
}
