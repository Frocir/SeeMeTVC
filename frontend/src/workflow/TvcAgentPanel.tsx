import { useEffect, useRef, useState } from "react";
import {
  api,
  clearAgentChat,
  patchAgentSession,
  streamAgentChat,
  streamAgentResume,
  type AgentConfirm,
  type AgentGraph,
  type AgentPlan,
  type AgentSessionOut,
  type AgentSkill,
  type AgentStageCard,
  type AgentUiMsg,
  type AgentViewport,
  type ModelOption,
} from "../api";
import { NODE_TYPE_LABEL } from "./labels";

type ToolLine = { name: string; status: string; detail: string };

const TOOL_NAME_ZH: Record<string, string> = {
  get_graph: "查看画布",
  add_node: "加步骤",
  patch_node: "改步骤",
  connect: "连线",
  delete_node: "删步骤",
  expand_scenes_to_nodes: "按分镜摆到画布",
  layout_graph: "排版",
  clear_chat: "清空对话",
  propose_plan: "写方案",
  complete_stage: "结束本环",
  get_node_output: "读取结果",
  list_asset_versions: "查看生成记录",
  send_asset_to_canvas: "放到画布",
  run_llm_text: "写镜头",
  run_text_to_image: "出图",
  run_image_compare: "对比图",
  run_image_to_video: "出视频",
  run_tts_speak: "配音",
  run_speech_to_text: "听写",
  run_video_trim: "裁视频",
  run_video_mux: "拼接",
  run_mix_audio: "混音",
  run_video_demux: "拆声音",
  run_video_reverse_prompt: "拆参考片",
  run_audio_trim: "裁音频",
  run_subtitle_burn: "加字幕",
};

const TOOL_STATUS_ZH: Record<string, string> = {
  running: "进行中",
  done: "完成",
  error: "失败",
  waiting: "等待确认",
};

type WorkMode = "auto" | "plan";

const WORK_MODES: { id: WorkMode; label: string; title: string }[] = [
  { id: "auto", label: "Auto", title: "不要计划，齐了就干，中途不停" },
  { id: "plan", label: "Plan", title: "先出计划，每环开始前要你点一下" },
];

function normalizeWorkMode(raw?: string): WorkMode {
  if (raw === "auto" || raw === "goal") return "auto";
  return "plan";
}

function formatToolLine(t: ToolLine): string {
  const name = TOOL_NAME_ZH[t.name] || t.name;
  const status = TOOL_STATUS_ZH[t.status] || t.status;
  return t.detail ? `${name} · ${status} · ${t.detail}` : `${name} · ${status}`;
}

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
    models[0]?.model_id || "";
  const [modelId, setModelId] = useState(preferred);
  const [skills, setSkills] = useState<AgentSkill[]>([]);
  const [skillId, setSkillId] = useState("");
  const [workMode, setWorkMode] = useState<WorkMode>("plan");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<AgentUiMsg[]>([]);
  const [streamText, setStreamText] = useState("");
  const [tools, setTools] = useState<ToolLine[]>([]);
  const [confirm, setConfirm] = useState<AgentConfirm | null>(null);
  const [plan, setPlan] = useState<AgentPlan | null>(null);
  const [stage, setStage] = useState<AgentStageCard | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const clearLock = useRef(false);

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
        setWorkMode(normalizeWorkMode(s.work_mode));
        if (s.model_id) setModelId(s.model_id);
        setConfirm(s.pending_confirm);
        setPlan(s.pending_plan || null);
        setStage(s.pending_stage || null);
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
          const i = prev.findIndex(
            (x) => x.name === ev.name && (x.status === "running" || x.status === "waiting"),
          );
          if (i >= 0) {
            const next = [...prev];
            next[i] = ev;
            return next;
          }
          return [...prev, ev];
        });
      },
      onGraph,
      onConfirm: (c: AgentConfirm) => {
        setConfirm(c);
        setPlan(null);
        setStage(null);
      },
      onPlan: (p: AgentPlan) => {
        setPlan(p);
        setStage(null);
        setConfirm(null);
      },
      onStage: (s: AgentStageCard) => {
        setStage(s);
        setPlan(null);
        setConfirm(null);
      },
      onChatCleared: () => {
        setMessages([]);
        setStreamText("");
        setTools([]);
        setConfirm(null);
        setPlan(null);
        setStage(null);
      },
      onError: (d: string) => setError(d),
      onDone: (status: string) => {
        setStreamText((text) => {
          if (text.trim()) {
            setMessages((ms) => [...ms, { id: Date.now(), role: "assistant", content: text }]);
          }
          return "";
        });
        if (status === "idle") {
          setPlan(null);
          setStage(null);
          setConfirm(null);
        }
        if (status === "confirm_pending") {
          setPlan(null);
          setStage(null);
        }
        setBusy(false);
        onLocked(status === "confirm_pending" || status === "running");
      },
    };
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy || !workflowId || confirm) return;
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
          work_mode: workMode,
          text,
          selected_node_id: selectedNodeId || "",
          viewport,
        },
        bindHandlers(),
        (abortRef.current = new AbortController()).signal,
      );
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "发送失败");
      setBusy(false);
      onLocked(false);
    } finally {
      areaRef.current?.focus();
    }
  }

  async function persistSession(patch: { skill_id?: string; work_mode?: WorkMode }) {
    if (!workflowId) return true;
    try {
      const out = await patchAgentSession(workflowId, patch);
      setError("");
      if (out.switch_auto) {
        void resumeAction("skip_to_auto");
      }
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法保存模式");
      return false;
    }
  }

  async function clearThread() {
    if (clearLock.current) return;
    clearLock.current = true;
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setStreamText("");
    setTools([]);
    setConfirm(null);
    setPlan(null);
    setStage(null);
    setBusy(false);
    onLocked(false);
    if (!workflowId) {
      setError("项目尚未打开");
      clearLock.current = false;
      return;
    }
    try {
      await clearAgentChat(workflowId);
      setError("");
    } catch {
      setError("");
    } finally {
      window.setTimeout(() => {
        clearLock.current = false;
      }, 400);
    }
  }

  function focusDraft() {
    areaRef.current?.focus();
  }

  async function resumeAction(action: string, accept = true) {
    if (!workflowId || busy) return;
    if (action === "revise") {
      focusDraft();
      return;
    }
    setBusy(true);
    onLocked(action === "approve" || action === "confirm" || action === "skip_to_auto");
    if (action === "cancel") {
      setPlan(null);
      setStage(null);
    }
    if (action === "confirm" || action === "reject") setConfirm(null);
    try {
      await streamAgentResume(
        {
          workflow_id: workflowId,
          accept,
          action,
          selected_node_id: selectedNodeId || "",
          viewport,
        },
        bindHandlers(),
        (abortRef.current = new AbortController()).signal,
      );
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "操作失败");
      setBusy(false);
      onLocked(false);
    }
  }

  async function resume(accept: boolean) {
    await resumeAction(accept ? "confirm" : "reject", accept);
  }

  return (
    <div className="cv-agent">
      <div className="cv-agent-skill">
        <span className="cv-agent-skill-k">Skill:</span>
        <div className="cv-agent-skill-pick">
          <select
            value={skillId}
            disabled={busy || !!confirm}
            onChange={(e) => {
              const next = e.target.value;
              setSkillId(next);
              void persistSession({ skill_id: next });
            }}
            aria-label="Skill"
          >
            <option value="">不指定 Skill</option>
            {skills.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          className="cv-agent-iconbtn"
          title="清空对话，画布不动"
          aria-label="清空对话"
          onPointerDown={(e) => {
            e.stopPropagation();
            void clearThread();
          }}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            void clearThread();
          }}
        >
          ×
        </button>
      </div>
      <div className="cv-agent-thread" ref={threadRef}>
        {messages.length === 0 && !busy && !streamText && !confirm && !plan && !stage && (
          <div className="cv-agent-empty">
            <p>你好，我是这条片子的主理人。</p>
            <p>先告诉我品牌和你想要的感觉，方案想清楚了我再去画布上搭。</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={`${m.role}-${m.id}-${i}`} className={`cv-agent-msg ${m.role}`}>
            <p>{m.content}</p>
          </div>
        ))}
        {tools.map((t, i) => (
          <div key={`tool-${i}`} className={`cv-agent-tool ${t.status}`}>
            {formatToolLine(t)}
          </div>
        ))}
        {(busy || streamText) && (
          <div className={`cv-agent-msg assistant ${streamText ? "" : "pending"}`}>
            <p>{streamText || "正在回复…"}</p>
          </div>
        )}
        {plan && !confirm && (
          <div className="cv-agent-confirm cv-agent-plan">
            <p>
              <strong>{plan.title || "片子方案"}</strong>
              {plan.rebuild ? " · 重搭画布" : ""}
            </p>
            {(plan.stages || []).map((s) => (
              <div key={s.id} className="cv-agent-plan-stage">
                <em>{s.title}</em>
                {s.points?.length ? (
                  <ul>
                    {s.points.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="cv-agent-confirm-meta">要点待补</span>
                )}
              </div>
            ))}
            <div className="cv-agent-confirm-actions">
              <button type="button" className="cv-agent-confirm-yes" disabled={busy} onClick={() => void resumeAction("approve")}>
                批准计划
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => focusDraft()}>
                先改
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => void resumeAction("cancel")}>
                取消
              </button>
            </div>
          </div>
        )}
        {stage && !confirm && !plan && (
          <div className="cv-agent-confirm cv-agent-plan">
            <p>
              下一环：<strong>{stage.title}</strong>
            </p>
            {stage.points?.length ? (
              <ul>
                {stage.points.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : (
              <p className="cv-agent-confirm-meta">点开始我就做这一环，出片还要再问你。</p>
            )}
            <div className="cv-agent-confirm-actions">
              <button type="button" className="cv-agent-confirm-yes" disabled={busy} onClick={() => void resumeAction("approve")}>
                {stage.start_label || "开始"}
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => focusDraft()}>
                先改
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => void resumeAction("cancel")}>
                取消计划
              </button>
            </div>
          </div>
        )}
        {confirm && (
          <div className="cv-agent-confirm">
            <p>
              要生成「{confirm.label}」了
              {confirm.node_type ? `（${NODE_TYPE_LABEL[confirm.node_type] || confirm.node_type}）` : ""}
            </p>
            <p className="cv-agent-confirm-wait">
              {confirm.message || "确认前不会开始生成，也不会扣费。"}
            </p>
            <p className="cv-agent-confirm-meta">
              模型 {confirm.model_id || "—"} · 预估 {confirm.estimated_cost} {confirm.unit || "积分"}
            </p>
            <div className="cv-agent-confirm-actions">
              <button type="button" className="cv-agent-confirm-yes" disabled={busy} onClick={() => void resume(true)}>
                确认开始
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
          disabled={busy || !workflowId || !!confirm}
          placeholder={
            workMode === "auto"
              ? "品牌、卖点、时长、画幅给我，我直接去搭"
              : "跟我说品牌和想要的感觉，我先帮你把方案想清楚"
          }
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
            className="cv-agent-mode-select"
            value={workMode}
            disabled={busy || !!confirm}
            title={
              WORK_MODES.find((m) => m.id === workMode)?.title +
              ((plan || stage) && workMode === "plan" ? "。切到 Auto 会立刻续跑" : "")
            }
            aria-label="工作模式"
            onChange={(e) => {
              const next = normalizeWorkMode(e.target.value);
              const prev = workMode;
              if (next === "auto" && (plan || stage)) {
                const ok = window.confirm("待批切到 Auto 会立刻续跑并跳过剩余创作闸门。若只想下次用 Auto，请先取消计划。");
                if (!ok) return;
              }
              setWorkMode(next);
              void persistSession({ work_mode: next }).then((ok) => {
                if (!ok) setWorkMode(prev);
              });
            }}
          >
            {WORK_MODES.map((m) => (
              <option key={m.id} value={m.id} title={m.title}>
                {m.label}
              </option>
            ))}
          </select>
          <select
            className="cv-agent-model"
            value={modelId}
            disabled={busy || models.length === 0}
            onChange={(e) => setModelId(e.target.value)}
            aria-label="对话模型"
          >
            {models.length === 0 && <option value="">无可用 LLM</option>}
            {models.map((opt) => (
              <option key={opt.model_id} value={opt.model_id}>
                {opt.label || opt.model_id}
              </option>
            ))}
          </select>
          {busy && workMode === "plan" && (
            <button
              type="button"
              className="cv-agent-stop"
              title="暂停，计划还在"
              onClick={() => void resumeAction("stop")}
            >
              停
            </button>
          )}
          <button
            type="submit"
            className="cv-agent-send"
            disabled={busy || !!confirm || !draft.trim() || models.length === 0 || !workflowId}
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
