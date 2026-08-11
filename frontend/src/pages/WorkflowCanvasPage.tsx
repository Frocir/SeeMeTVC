import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  api,
  isActiveRun,
  isTerminalRun,
  STATUS_LABEL,
  subscribeWorkflowRun,
  type ModelOption,
  type Workflow,
  type WorkflowRun,
} from "../api";
import { useAuth } from "../auth";
import { ensureUpstreamImageUrl } from "../imageUrl";
import AdminSimulateDialog from "../workflow/AdminSimulateDialog";
import { mediaNodeTypes } from "../workflow/canvas/MediaNode";
import { fromApiGraph, toApiGraph } from "../workflow/graph";
import { isValidPortConnection } from "../workflow/ports";
import {
  collectDownstreamExitIds,
  exitInputsReady,
  inputFingerprint,
  markDownstreamStale,
} from "../workflow/queue";
import type { WfData, WfNodeType } from "../workflow/types";
import { isExitNodeType, normalizeNodeType } from "../workflow/types";
import WfInspector from "../workflow/WfInspector";
import {
  PALETTE,
  WF_TEMPLATES,
  defaultData,
  defaultGraph,
  type WfTemplateId,
} from "../workflow/templates";

function applyMediaFromOutput(data: WfData, output?: Record<string, unknown> | null): WfData {
  if (!output) return data;
  const next = { ...data, runOutput: output, stale: false, simulated: false };
  const clips = output.clips;
  if (Array.isArray(clips) && typeof clips[0] === "string") {
    next.clip_url = clips[0] as string;
    next.preview_url = clips[0] as string;
  }
  if (typeof output.clip_url === "string") {
    next.clip_url = output.clip_url;
    next.preview_url = output.clip_url;
  }
  if (typeof output.result_url === "string") {
    next.result_url = output.result_url;
    next.preview_url = output.result_url;
  }
  if (typeof output.image_url === "string") {
    next.image_url = output.image_url;
  }
  if (typeof output.prompt === "string" && normalizeNodeType(data.nodeType) === "TextAsset") {
    next.prompt = output.prompt;
    next.text = output.prompt;
  }
  return next;
}

export default function WorkflowCanvasPage() {
  const { me, refresh } = useAuth();
  const isAdmin = me?.role === "super_admin";
  const [models, setModels] = useState<ModelOption[]>([]);
  const [name, setName] = useState("美妆 TVC 画布");
  const [workflowId, setWorkflowId] = useState<number | null>(null);
  const [savedList, setSavedList] = useState<Workflow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [queueNote, setQueueNote] = useState("");
  const [activeTemplate, setActiveTemplate] = useState<WfTemplateId>("beauty_linear");
  const [flowKey, setFlowKey] = useState(0);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [fullscreen, setFullscreen] = useState<{ url: string; kind: "image" | "video" } | null>(
    null,
  );
  const [simulate, setSimulate] = useState<{
    nodeId: string;
    label: string;
    message: string;
  } | null>(null);
  const idSeq = useRef(1);
  const fingerprints = useRef<Record<string, string>>({});
  const autoArmed = useRef(false);
  const runningRef = useRef(false);
  /** Suppress auto-queue after manual/template runs so we don't double-hit Agnes. */
  const suppressAutoUntil = useRef(0);
  const lastSimulatedRunId = useRef<number | null>(null);

  const modelId = models[0]?.model_id || "";
  const seed = useMemo(() => defaultGraph(modelId), [modelId]);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<WfData>>(seed.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(seed.edges);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([
      api<ModelOption[]>("/api/models"),
      api<Workflow[]>("/api/workflows"),
    ]).then(([m, wfs]) => {
      setModels(m);
      setSavedList(wfs);
      const mid = m[0]?.model_id || "";
      if (!workflowId) {
        const g = defaultGraph(mid);
        setNodes(g.nodes);
        setEdges(g.edges);
        for (const n of g.nodes) {
          if (isExitNodeType(n.data.nodeType)) {
            fingerprints.current[n.id] = inputFingerprint(n.id, g.nodes, g.edges);
          }
        }
        autoArmed.current = true;
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = useMemo(
    () => nodes.find((n) => n.id === selectedId) ?? null,
    [nodes, selectedId],
  );

  const displayNodes = useMemo(
    () =>
      nodes.map((n) => ({
        ...n,
        data: {
          ...n.data,
          onLabelChange: (label: string) => {
            setNodes((nds) =>
              nds.map((x) => (x.id === n.id ? { ...x, data: { ...x.data, label } } : x)),
            );
          },
          onOpenFullscreen: (url: string, kind: "image" | "video") => setFullscreen({ url, kind }),
        },
      })),
    [nodes, setNodes],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (!isValidPortConnection(c)) return;
      setEdges((eds) =>
        addEdge(
          {
            ...c,
            id: `e-${Date.now()}`,
            sourceHandle: c.sourceHandle ?? undefined,
            targetHandle: c.targetHandle ?? undefined,
            animated: true,
          },
          eds,
        ),
      );
      if (c.target) {
        setNodes((ns) => markDownstreamStale(c.source || "", ns, edges));
      }
    },
    [setEdges, setNodes, edges],
  );

  function applyTemplate(id: WfTemplateId) {
    const tpl = WF_TEMPLATES.find((t) => t.id === id);
    if (!tpl) return;
    const g = tpl.build(modelId);
    setNodes(g.nodes);
    setEdges(g.edges);
    setActiveTemplate(id);
    setSelectedId(null);
    setRun(null);
    setName(tpl.name);
    fingerprints.current = {};
    for (const n of g.nodes) {
      if (isExitNodeType(n.data.nodeType)) {
        fingerprints.current[n.id] = inputFingerprint(n.id, g.nodes, g.edges);
      }
    }
    autoArmed.current = true;
    // Remount flow so fitView re-frames the new layout
    setFlowKey((k) => k + 1);
  }

  function addNode(type: WfNodeType) {
    const id = `n${Date.now()}-${idSeq.current++}`;
    setNodes((ns) => [
      ...ns,
      {
        id,
        type: "media",
        position: { x: 180 + (ns.length % 5) * 48, y: 120 + (ns.length % 4) * 48 },
        data: defaultData(type, modelId),
      },
    ]);
    setSelectedId(id);
  }

  function updateSelected(patch: Partial<WfData>) {
    if (!selectedId) return;
    setNodes((ns) => {
      const next = ns.map((n) =>
        n.id === selectedId ? { ...n, data: { ...n.data, ...patch } } : n,
      );
      return markDownstreamStale(selectedId, next, edges);
    });
  }

  function applyRunStates(r: WorkflowRun) {
    setNodes((ns) =>
      ns.map((n) => {
        const st = r.node_states?.[n.id];
        if (!st) return n;
        const withMedia = applyMediaFromOutput(
          {
            ...n.data,
            runStatus: st.status,
            runError: st.error || (st.status === "running" ? st.hint || undefined : undefined),
          },
          st.output,
        );
        if (r.result_url && normalizeNodeType(n.data.nodeType) === "VideoAsset") {
          withMedia.result_url = withMedia.result_url || r.result_url;
          withMedia.preview_url = withMedia.preview_url || r.result_url;
        }
        return { ...n, data: withMedia };
      }),
    );

    if (
      isAdmin &&
      isTerminalRun(r.status) &&
      (r.status === "failed" || r.status === "refunded") &&
      lastSimulatedRunId.current !== r.id
    ) {
      const failedId =
        Object.entries(r.node_states || {}).find(([, st]) => st.status === "failed")?.[0] || null;
      if (failedId) {
        lastSimulatedRunId.current = r.id;
        const node = nodes.find((n) => n.id === failedId);
        setSimulate({
          nodeId: failedId,
          label: node?.data.label || failedId,
          message: r.error_message || node?.data.runError || "生成失败",
        });
      }
    }
  }

  async function prepareGraph(targetIds?: string[]) {
    const graph = toApiGraph(nodes, edges);
    const patchedNodes: typeof graph.nodes = [];
    for (const n of graph.nodes) {
      const d = { ...(n.data as WfData) };
      if (normalizeNodeType(d.nodeType) === "ImageToVideo" && !d.model_id) d.model_id = modelId;
      if (d.image_url) {
        d.image_url = (await ensureUpstreamImageUrl(d.image_url)) || undefined;
      }
      patchedNodes.push({ ...n, data: d });
    }
    setNodes((ns) =>
      ns.map((node) => {
        const fresh = patchedNodes.find((p) => p.id === node.id);
        if (!fresh) return node;
        const fd = fresh.data as WfData;
        if (fd.image_url && fd.image_url !== node.data.image_url) {
          return { ...node, data: { ...node.data, image_url: fd.image_url } };
        }
        return node;
      }),
    );
    return {
      graph: { ...graph, nodes: patchedNodes },
      targetIds,
    };
  }

  async function startRun(targetIds?: string[], note?: string) {
    if (runningRef.current) {
      setQueueNote("队列忙碌：已有任务在执行");
      return;
    }
    setBusy(true);
    setError("");
    setSimulate(null);
    setQueueNote(note || (targetIds ? `队列：运行 ${targetIds.length} 个节点` : "队列：一键跑模板"));
    runningRef.current = true;
    // Full template / manual runs: pause auto-queue so it cannot open a 2nd Agnes poller
    suppressAutoUntil.current = Date.now() + (targetIds ? 15_000 : 120_000);
    try {
      const { graph } = await prepareGraph(targetIds);
      const r = await api<WorkflowRun>("/api/workflows/runs", {
        method: "POST",
        body: JSON.stringify({
          workflow_id: workflowId,
          graph,
          name,
          target_ids: targetIds,
        }),
      });
      setRun(r);
      applyRunStates(r);
      if (r.workflow_id) setWorkflowId(r.workflow_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "执行失败");
      runningRef.current = false;
      if (isAdmin) {
        const sid = targetIds?.[0] || selectedId;
        if (sid) {
          const node = nodes.find((n) => n.id === sid);
          setSimulate({
            nodeId: sid,
            label: node?.data.label || sid,
            message: e instanceof Error ? e.message : "执行失败",
          });
        }
      }
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    setBusy(true);
    setError("");
    try {
      const graph = toApiGraph(nodes, edges);
      if (workflowId) {
        const wf = await api<Workflow>(`/api/workflows/${workflowId}`, {
          method: "PATCH",
          body: JSON.stringify({ name, graph }),
        });
        setWorkflowId(wf.id);
      } else {
        const wf = await api<Workflow>("/api/workflows", {
          method: "POST",
          body: JSON.stringify({ name, graph }),
        });
        setWorkflowId(wf.id);
      }
      setSavedList(await api<Workflow[]>("/api/workflows"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function loadWorkflow(id: number) {
    setError("");
    try {
      const wf = await api<Workflow>(`/api/workflows/${id}`);
      setWorkflowId(wf.id);
      setName(wf.name);
      const g = fromApiGraph(wf.graph, modelId);
      setNodes(g.nodes);
      setEdges(g.edges);
      setRun(null);
      setSelectedId(null);
      fingerprints.current = {};
      for (const n of g.nodes) {
        if (isExitNodeType(n.data.nodeType)) {
          fingerprints.current[n.id] = inputFingerprint(n.id, g.nodes, g.edges);
        }
      }
      autoArmed.current = true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }

  async function cancelRun() {
    if (!run || !isActiveRun(run.status)) return;
    try {
      const fresh = await api<WorkflowRun>(`/api/workflows/runs/${run.id}/cancel`, {
        method: "POST",
      });
      setRun(fresh);
      applyRunStates(fresh);
      runningRef.current = false;
      setQueueNote("已取消当前任务");
    } catch (e) {
      setError(e instanceof Error ? e.message : "取消失败");
    }
  }

  const runActive = !!(run && isActiveRun(run.status));

  useEffect(() => {
    if (!run || !runActive) {
      if (run && isTerminalRun(run.status)) {
        runningRef.current = false;
        for (const n of nodes) {
          if (isExitNodeType(n.data.nodeType)) {
            fingerprints.current[n.id] = inputFingerprint(n.id, nodes, edges);
          }
        }
      }
      return;
    }
    const stop = subscribeWorkflowRun(run.id, async (fresh) => {
      setRun(fresh);
      applyRunStates(fresh);
      if (isTerminalRun(fresh.status)) {
        runningRef.current = false;
        await refresh();
      }
    });
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, runActive, refresh]);

  // Auto-queue exit nodes when inputs change (Q12=C / Q17=A)
  useEffect(() => {
    if (!autoArmed.current || runningRef.current || busy) return;
    if (Date.now() < suppressAutoUntil.current) return;
    const due: string[] = [];
    for (const n of nodes) {
      if (!isExitNodeType(n.data.nodeType)) continue;
      if (!exitInputsReady(n.id, nodes, edges)) continue;
      const fp = inputFingerprint(n.id, nodes, edges);
      const prev = fingerprints.current[n.id];
      if (prev == null) {
        fingerprints.current[n.id] = fp;
        continue;
      }
      if (fp !== prev) due.push(n.id);
    }
    if (!due.length) return;
    for (const id of due) {
      fingerprints.current[id] = inputFingerprint(id, nodes, edges);
    }
    void startRun(due, `自动队列：${due.join(", ")}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  function applySimulate(url: string, continueDownstream: boolean) {
    if (!simulate) return;
    const nid = simulate.nodeId;
    const isVid = /\.(mp4|webm|mov)(\?|$)/i.test(url) || url.includes("/uploads/");
    setNodes((ns) =>
      ns.map((n) => {
        if (n.id !== nid) return n;
        const nt = normalizeNodeType(n.data.nodeType);
        if (nt === "ImageAsset" || (!isVid && nt !== "ImageToVideo" && nt !== "VideoMux" && nt !== "VideoTrim" && nt !== "VideoAsset")) {
          return {
            ...n,
            data: {
              ...n.data,
              image_url: url,
              runStatus: "succeeded",
              runError: undefined,
              stale: false,
              simulated: true,
            },
          };
        }
        return {
          ...n,
          data: {
            ...n.data,
            clip_url: url,
            result_url: url,
            preview_url: url,
            runStatus: "succeeded",
            runError: undefined,
            stale: false,
            simulated: true,
          },
        };
      }),
    );
    setSimulate(null);
    if (continueDownstream) {
      const next = collectDownstreamExitIds(nid, nodes, edges);
      if (next.length) void startRun(next, "模拟填入后继续下游");
    }
  }

  const selectedCanGenerate =
    !!selected &&
    (isExitNodeType(selected.data.nodeType) ||
      normalizeNodeType(selected.data.nodeType) === "TextAsset");

  return (
    <div className={`cv-stage ${leftOpen ? "left-open" : "left-collapsed"} ${rightOpen ? "right-open" : "right-collapsed"}`}>
      <section className="cv-canvas">
        <ReactFlow
          key={flowKey}
          nodes={displayNodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidPortConnection}
          nodeTypes={mediaNodeTypes}
          onNodeClick={(_, n) => {
            setSelectedId(n.id);
            setRightOpen(true);
          }}
          onPaneClick={() => setSelectedId(null)}
          fitView
          fitViewOptions={{ padding: 0.18, maxZoom: 1 }}
          minZoom={0.15}
          maxZoom={2}
          defaultEdgeOptions={{
            animated: true,
            style: { stroke: "rgba(212, 87, 138, 0.45)", strokeWidth: 1.75 },
          }}
          proOptions={{ hideAttribution: true }}
          colorMode="light"
          className="cv-flow"
        >
          <Background
            id="cv-grid"
            variant={BackgroundVariant.Dots}
            gap={28}
            size={1.1}
            color="rgba(212, 87, 138, 0.18)"
          />
          <Controls showInteractive={false} position="bottom-left" />
          <MiniMap
            pannable
            zoomable
            maskColor="rgba(250, 247, 248, 0.72)"
            nodeColor={() => "#d4578a"}
            style={{ background: "#fff9fb" }}
            position="bottom-right"
          />
        </ReactFlow>
      </section>

      {/* Floating top status strip */}
      <div className="cv-topbar">
        <div className="cv-topbar-brand">画布</div>
        <input
          className="cv-topbar-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="项目名称"
        />
        <div className="cv-topbar-queue">
          {run && isActiveRun(run.status)
            ? `${STATUS_LABEL[run.status] || run.status} · #${run.id}`
            : queueNote || "队列空闲"}
        </div>
        <div className="cv-topbar-actions">
          {run && isActiveRun(run.status) && (
            <button type="button" className="cv-chip-btn" onClick={() => void cancelRun()}>
              取消
            </button>
          )}
          <button type="button" className="cv-chip-btn" disabled={busy} onClick={() => void saveDraft()}>
            保存
          </button>
          <button
            type="button"
            className="cv-chip-btn primary"
            disabled={busy || !modelId || (!!run && isActiveRun(run.status))}
            title={!modelId ? "暂无可用模型，请先在超管启用渠道" : undefined}
            onClick={() => void startRun(undefined, "一键跑模板")}
          >
            一键跑
          </button>
        </div>
      </div>

      {!modelId && (
        <div className="cv-model-empty" role="status">
          <strong>暂无可用模型</strong>
          <span>
            图生视频无法运行。请超管启用渠道（本地优先 mock）
            {isAdmin ? (
              <>
                ，或打开 <Link to="/admin">超管</Link>
              </>
            ) : (
              "。"
            )}
          </span>
        </div>
      )}

      {/* Left rail: collapses to a fixed icon strip (always hoverable) */}
      <aside className={`cv-dock ${leftOpen ? "is-open" : "is-collapsed"}`}>
        {leftOpen ? (
          <>
            <div className="cv-dock-head">
              <div>
                <p className="eyebrow">工具箱</p>
                <strong>添加与模板</strong>
              </div>
              <button
                type="button"
                className="cv-panel-toggle"
                aria-label="收起左侧工具栏"
                title="收起"
                onClick={() => setLeftOpen(false)}
              >
                ‹
              </button>
            </div>
            <div className="cv-dock-scroll">
              <div className="cv-section">
                <p className="eyebrow">模板</p>
                <div className="cv-templates">
                  {WF_TEMPLATES.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      className={`cv-tpl ${activeTemplate === t.id ? "active" : ""}`}
                      onClick={() => applyTemplate(t.id)}
                    >
                      <strong>{t.name}</strong>
                      <span>{t.hint}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="cv-section">
                <p className="eyebrow">添加节点</p>
                <div className="cv-palette">
                  {PALETTE.map((p) => (
                    <button key={p.type} type="button" className="cv-add" onClick={() => addNode(p.type)}>
                      <strong>{p.label}</strong>
                      <span>{p.hint}</span>
                    </button>
                  ))}
                </div>
              </div>
              {savedList.length > 0 && (
                <div className="cv-section">
                  <p className="eyebrow">草稿</p>
                  <div className="cv-saved">
                    {savedList.slice(0, 6).map((w) => (
                      <button
                        key={w.id}
                        type="button"
                        className="cv-draft"
                        onClick={() => void loadWorkflow(w.id)}
                      >
                        {w.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {error && <p className="error">{error}</p>}
              {run && (
                <div className="cv-run">
                  <p>
                    #{run.id} · <strong>{STATUS_LABEL[run.status] || run.status}</strong>
                    {run.cost > 0 && <> · {run.cost.toFixed(2)}</>}
                  </p>
                  {run.error_message && <p className="error">{run.error_message}</p>}
                </div>
              )}
            </div>
          </>
        ) : (
          <button
            type="button"
            className="cv-rail-expand"
            aria-label="展开左侧工具栏"
            title="展开工具栏"
            onClick={() => setLeftOpen(true)}
          >
            <span className="cv-rail-expand-chevron">›</span>
            <span className="cv-rail-expand-text">工具</span>
          </button>
        )}
      </aside>

      {/* Right inspector: collapses to fixed strip */}
      <div className={`cv-inspector ${rightOpen ? "is-open" : "is-collapsed"}`}>
        {rightOpen ? (
          <>
            <div className="cv-dock-head">
              <div>
                <p className="eyebrow">属性</p>
                <strong>{selected?.data.label || "未选中节点"}</strong>
              </div>
              <button
                type="button"
                className="cv-panel-toggle"
                aria-label="收起属性面板"
                title="收起"
                onClick={() => setRightOpen(false)}
              >
                ›
              </button>
            </div>
            <div className="cv-dock-scroll">
              <WfInspector
                data={selected?.data ?? null}
                models={models}
                modelId={modelId}
                onChange={updateSelected}
                onGenerate={
                  selectedCanGenerate
                    ? () => {
                        if (!selectedId) return;
                        void startRun([selectedId], "生成选中节点");
                      }
                    : undefined
                }
                canGenerate={selectedCanGenerate && !busy && !(run && isActiveRun(run.status))}
                onDelete={() => {
                  setNodes((ns) => ns.filter((n) => n.id !== selectedId));
                  setEdges((es: Edge[]) =>
                    es.filter((e) => e.source !== selectedId && e.target !== selectedId),
                  );
                  setSelectedId(null);
                }}
              />
            </div>
          </>
        ) : (
          <button
            type="button"
            className="cv-rail-expand"
            aria-label="展开属性面板"
            title="展开属性"
            onClick={() => setRightOpen(true)}
          >
            <span className="cv-rail-expand-text">属性</span>
            <span className="cv-rail-expand-chevron">‹</span>
          </button>
        )}
      </div>

      {fullscreen && (
        <div className="cv-modal-backdrop" onClick={() => setFullscreen(null)}>
          <div className="cv-fullscreen" onClick={(e) => e.stopPropagation()}>
            {fullscreen.kind === "video" ? (
              <video src={fullscreen.url} controls autoPlay />
            ) : (
              <img src={fullscreen.url} alt="" />
            )}
          </div>
        </div>
      )}

      <AdminSimulateDialog
        open={!!simulate}
        nodeLabel={simulate?.label || ""}
        errorMessage={simulate?.message || ""}
        onClose={() => setSimulate(null)}
        onApply={applySimulate}
      />
    </div>
  );
}
