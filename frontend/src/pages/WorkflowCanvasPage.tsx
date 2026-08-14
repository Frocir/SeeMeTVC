import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  api,
  expandScenesToNodes,
  isActiveRun,
  isTerminalRun,
  STATUS_LABEL,
  subscribeWorkflowRun,
  type AgentGraph,
  type AgentViewport,
  type ModelOption,
  type Workflow,
  type WorkflowRun,
} from "../api";
import { useAuth } from "../auth";
import { ensureUpstreamImageUrl } from "../imageUrl";
import AdminSimulateDialog from "../workflow/AdminSimulateDialog";
import { mediaNodeTypes } from "../workflow/canvas/MediaNode";
import { fromApiGraph, toApiGraph } from "../workflow/graph";
import { dropClosedNarrationEdges, isValidPortConnection } from "../workflow/ports";
import { inferConnectionHandles, syncWiredData } from "../workflow/sync";
import {
  collectDownstreamExitIds,
  exitInputsReady,
  inputFingerprint,
  markDownstreamStale,
} from "../workflow/queue";
import type { WfData, WfNodeType } from "../workflow/types";
import { isExitNodeType, isGeneratableNodeType, isLlmNodeType, normalizeNodeType } from "../workflow/types";
import { cannotRunReason } from "../workflow/runBlockers";
import type { NodeContracts } from "../workflow/nodeContracts";
import WfInspector from "../workflow/WfInspector";
import ProjectAssetPanel from "../workflow/ProjectAssetPanel";
import TvcAgentPanel from "../workflow/TvcAgentPanel";
import { PALETTE, defaultData } from "../workflow/templates";

function ViewportReporter({ onChange }: { onChange: (p: AgentViewport) => void }) {
  const rf = useReactFlow();
  useEffect(() => {
    const tick = () => {
      const el = document.querySelector(".cv-flow");
      if (!(el instanceof HTMLElement)) return;
      const r = el.getBoundingClientRect();
      const p = rf.screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
      onChange({ x: p.x, y: p.y });
    };
    tick();
    const id = window.setInterval(tick, 800);
    return () => window.clearInterval(id);
  }, [rf, onChange]);
  return null;
}

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
  if (typeof output.prompt === "string" && (normalizeNodeType(data.nodeType) === "TextAsset" || isLlmNodeType(data.nodeType))) {
    next.prompt = output.prompt;
    next.text = typeof output.text === "string" ? output.text : output.prompt;
  }
  if (typeof output.text === "string" && isLlmNodeType(data.nodeType)) {
    next.text = output.text;
    next.prompt = next.prompt || output.text;
  }
  if (data.wantNarration === false) {
    next.narration = "";
  } else if (typeof output.narration === "string") {
    next.narration = output.narration;
  }
  if (typeof output.audio_url === "string") next.audio_url = output.audio_url;
  return next;
}

export default function WorkflowCanvasPage() {
  const { me, refresh } = useAuth();
  const isAdmin = me?.role === "super_admin";
  const { workflowId: idParam } = useParams();
  const navigate = useNavigate();
  const routeId = Number(idParam);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [llmModels, setLlmModels] = useState<ModelOption[]>([]);
  const [ttsModels, setTtsModels] = useState<ModelOption[]>([]);
  const [imageModels, setImageModels] = useState<ModelOption[]>([]);
  const [contracts, setContracts] = useState<NodeContracts | null>(null);
  const [name, setName] = useState("未命名项目");
  const [workflowId, setWorkflowId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [queueNote, setQueueNote] = useState("");
  const [flowKey, setFlowKey] = useState(0);
  const [leftOpen, setLeftOpen] = useState(true);
  const [leftTab, setLeftTab] = useState<"agent" | "nodes" | "assets">("agent");
  const [assetTick, setAssetTick] = useState(0);
  const [fullscreen, setFullscreen] = useState<{ url: string; kind: "image" | "video" | "audio" } | null>(
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
  const llmModelId = llmModels[0]?.model_id || "";
  const ttsModelId = ttsModels[0]?.model_id || "tts-1";
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<WfData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [agentLocked, setAgentLocked] = useState(false);
  const [viewport, setViewport] = useState<AgentViewport>({ x: 400, y: 280 });
  const lastSavedRef = useRef("");
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  nodesRef.current = nodes;
  edgesRef.current = edges;
  const onViewport = useCallback((p: AgentViewport) => setViewport(p), []);

  useEffect(() => {
    if (!Number.isFinite(routeId) || routeId <= 0) {
      navigate("/", { replace: true });
      return;
    }
    void Promise.all([
      api<ModelOption[]>("/api/models?kind=video"),
      api<ModelOption[]>("/api/models?kind=llm"),
      api<ModelOption[]>("/api/models?kind=tts"),
      api<ModelOption[]>("/api/models?kind=image"),
      api<Workflow>(`/api/workflows/${routeId}`),
      api<NodeContracts>("/api/agent/node-contracts"),
    ])
      .then(([m, llm, tts, imgs, wf, cons]) => {
        setModels(m);
        setLlmModels(llm);
        setTtsModels(tts);
        setImageModels(imgs);
        setContracts(cons);
        const mid = m[0]?.model_id || "";
        setWorkflowId(wf.id);
        setName(wf.name);
        const g = fromApiGraph(wf.graph, mid);
        setNodes(g.nodes);
        setEdges(g.edges);
        lastSavedRef.current = JSON.stringify(toApiGraph(g.nodes, g.edges));
        setFlowKey((k) => k + 1);
        fingerprints.current = {};
        for (const n of g.nodes) {
          if (isExitNodeType(n.data.nodeType)) {
            fingerprints.current[n.id] = inputFingerprint(n.id, g.nodes, g.edges);
          }
        }
        autoArmed.current = true;
      })
      .catch(() => navigate("/", { replace: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeId]);

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
          onOpenFullscreen: (url: string, kind: "image" | "video" | "audio") => setFullscreen({ url, kind }),
        },
      })),
    [nodes, setNodes],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      const wired = inferConnectionHandles(c, nodes, edges, contracts);
      if (!isValidPortConnection(wired, nodes, edges, contracts)) return;
      const nextEdges = addEdge(
        {
          ...wired,
          id: `e-${Date.now()}`,
          sourceHandle: wired.sourceHandle ?? undefined,
          targetHandle: wired.targetHandle ?? undefined,
          animated: true,
        },
        edges,
      );
      setEdges(nextEdges);
      setNodes((ns) => {
        const stale = wired.source ? markDownstreamStale(wired.source, ns, nextEdges) : ns;
        return syncWiredData(stale, nextEdges);
      });
    },
    [setEdges, setNodes, edges, nodes, contracts],
  );

  function addNode(type: WfNodeType, extra?: Partial<WfData>) {
    const id = `n${Date.now()}-${idSeq.current++}`;
    setNodes((ns) => [
      ...ns,
      {
        id,
        type: "media",
        position: { x: 180 + (ns.length % 5) * 48, y: 120 + (ns.length % 4) * 48 },
        data: { ...defaultData(type, modelId), ...extra },
      },
    ]);
    setSelectedId(id);
  }

  function updateSelected(patch: Partial<WfData>) {
    if (!selectedId) return;
    const nextEdges =
      patch.wantNarration === false
        ? dropClosedNarrationEdges([{ id: selectedId, data: patch }], edges)
        : edges;
    if (nextEdges !== edges) setEdges(nextEdges);
    setNodes((ns) => {
      const next = ns.map((n) =>
        n.id === selectedId ? { ...n, data: { ...n.data, ...patch } } : n,
      );
      return syncWiredData(markDownstreamStale(selectedId, next, nextEdges), nextEdges);
    });
  }

  function applyRunStates(r: WorkflowRun) {
    setNodes((ns) => {
      const applied = ns.map((n) => {
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
      });
      return syncWiredData(applied, edges);
    });

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
      if (isLlmNodeType(d.nodeType) && !d.model_id) d.model_id = llmModelId;
      if (normalizeNodeType(d.nodeType) === "TtsSpeak" && !d.model_id) d.model_id = ttsModelId;
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
    const blocked = cannotRunReason(nodes, edges, {
      modelId,
      llmReady: llmModels.length > 0,
      ttsReady: ttsModels.length > 0,
      imageReady: imageModels.length > 0,
      targetIds,
      contracts,
    });
    if (blocked) {
      setError(blocked);
      setQueueNote("无法生成");
      return;
    }
    if (runningRef.current) {
      setQueueNote("队列忙碌：已有任务在执行");
      return;
    }
    setBusy(true);
    setError("");
    setSimulate(null);
    setQueueNote(note || (targetIds ? `队列：运行 ${targetIds.length} 个节点` : "队列：一键跑"));
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

  async function saveDraft(opts?: { silent?: boolean }) {
    if (!opts?.silent) {
      setBusy(true);
      setError("");
    }
    try {
      const graph = toApiGraph(nodesRef.current, edgesRef.current);
      if (!workflowId) throw new Error("项目尚未打开");
      const wf = await api<Workflow>(`/api/workflows/${workflowId}`, {
        method: "PATCH",
        body: JSON.stringify({ name, graph }),
      });
      setWorkflowId(wf.id);
      setName(wf.name);
      lastSavedRef.current = JSON.stringify(graph);
      setAssetTick((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
      throw e;
    } finally {
      if (!opts?.silent) setBusy(false);
    }
  }

  async function expandSelectedScenes(mode: "silent" | "with_image" | "with_tts" | "full_tvc") {
    if (!workflowId || !selectedId || agentLocked) return;
    setBusy(true);
    setError("");
    try {
      await saveDraft({ silent: true });
      const out = await expandScenesToNodes(workflowId, selectedId, mode);
      const mid = models[0]?.model_id || "";
      const g = fromApiGraph(out.graph, mid);
      setNodes(g.nodes);
      setEdges(g.edges);
      lastSavedRef.current = JSON.stringify(toApiGraph(g.nodes, g.edges));
      setSelectedId(out.final_node_id || out.created_node_ids[0] || selectedId);
      setAssetTick((n) => n + 1);
      setQueueNote(`已从分镜生成 ${out.created_node_ids.length} 个节点`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "展开分镜失败");
    } finally {
      setBusy(false);
    }
  }

  async function undoDraft() {
    if (!workflowId || agentLocked) return;
    setBusy(true);
    setError("");
    try {
      const wf = await api<Workflow>(`/api/workflows/${workflowId}/undo`, { method: "POST" });
      const mid = models[0]?.model_id || "";
      const g = fromApiGraph(wf.graph, mid);
      setNodes(g.nodes);
      setEdges(g.edges);
      lastSavedRef.current = JSON.stringify(toApiGraph(g.nodes, g.edges));
      setAssetTick((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "撤销失败");
    } finally {
      setBusy(false);
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
        if (fresh.status === "succeeded") setAssetTick((n) => n + 1);
      }
    });
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, runActive, refresh]);

  // Auto-queue exit nodes when inputs change (Q12=C / Q17=A)
  useEffect(() => {
    if (!autoArmed.current || runningRef.current || busy || agentLocked) return;
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
  }, [nodes, edges, agentLocked]);

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

  const runBlock = useMemo(
    () =>
      cannotRunReason(nodes, edges, {
        modelId,
        llmReady: llmModels.length > 0,
        ttsReady: ttsModels.length > 0,
        imageReady: imageModels.length > 0,
        contracts,
      }),
    [nodes, edges, modelId, llmModels.length, ttsModels.length, imageModels.length, contracts],
  );

  const selectedCanGenerate =
    !!selected && isGeneratableNodeType(selected.data.nodeType);

  return (
    <div className="canvas-app">
    <div className={`cv-stage ${leftOpen ? "left-open" : "left-collapsed"} ${selected ? "right-open" : ""}`}>
      <section className="cv-canvas">
        <ReactFlow
          key={flowKey}
          nodes={displayNodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodesDraggable={!agentLocked}
          nodesConnectable={!agentLocked}
          edgesReconnectable={!agentLocked}
          elementsSelectable
          onConnect={agentLocked ? undefined : onConnect}
          isValidConnection={(c) => isValidPortConnection(c, nodes, edges, contracts)}
          nodeTypes={mediaNodeTypes}
          onNodeClick={(_, n) => setSelectedId(n.id)}
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
          <ViewportReporter onChange={onViewport} />
          <Background
            id="cv-grid"
            variant={BackgroundVariant.Dots}
            gap={28}
            size={1.1}
            color="rgba(212, 87, 138, 0.18)"
          />
          <Controls showInteractive={false} position="bottom-right" />
          <MiniMap
            pannable
            zoomable
            maskColor="rgba(36, 30, 34, 0.38)"
            maskStrokeColor="#241e22"
            maskStrokeWidth={2}
            nodeColor={() => "#d4578a"}
            style={{ background: "#fff9fb" }}
            position="bottom-right"
          />
        </ReactFlow>
      </section>

      {/* Floating top status strip */}
      <div className="cv-topbar">
        <Link to="/" className="cv-chip-btn">
          ← 工作区
        </Link>
        <input
          className="cv-topbar-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="项目名称"
        />
        <div className="cv-topbar-queue">
          {run && isActiveRun(run.status)
            ? STATUS_LABEL[run.status] || run.status
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
          <button type="button" className="cv-chip-btn" disabled={busy || agentLocked} onClick={() => void undoDraft()}>
            撤销
          </button>
          <button
            type="button"
            className="cv-chip-btn primary"
            disabled={busy || (!!run && isActiveRun(run.status))}
            title={runBlock || undefined}
            onClick={() => void startRun(undefined, "一键跑")}
          >
            一键跑
          </button>
        </div>
      </div>

      {(runBlock || error) && (
        <div className="cv-model-empty" role="alert">
          <strong>无法生成</strong>
          <span>
            {error || runBlock}
            {!modelId && isAdmin && (
              <>
                {" "}
                打开 <Link to="/admin">超管</Link>
              </>
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
                <p className="eyebrow">项目</p>
                <strong>{leftTab === "agent" ? "TVC Agent" : leftTab === "assets" ? "素材" : "节点"}</strong>
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
            <div className="cv-dock-tabs">
              <button
                type="button"
                className={leftTab === "agent" ? "active" : ""}
                onClick={() => setLeftTab("agent")}
              >
                TVC Agent
              </button>
              <button
                type="button"
                className={leftTab === "nodes" ? "active" : ""}
                onClick={() => setLeftTab("nodes")}
              >
                节点
              </button>
              <button
                type="button"
                className={leftTab === "assets" ? "active" : ""}
                onClick={() => setLeftTab("assets")}
              >
                素材
              </button>
            </div>
            {leftTab === "agent" ? (
              <TvcAgentPanel
                workflowId={workflowId}
                models={llmModels}
                selectedNodeId={selectedId}
                viewport={viewport}
                onGraph={(graph: AgentGraph) => {
                  const mid = models[0]?.model_id || "";
                  const g = fromApiGraph(graph, mid);
                  setNodes(g.nodes);
                  setEdges(g.edges);
                  lastSavedRef.current = JSON.stringify(toApiGraph(g.nodes, g.edges));
                  for (const n of g.nodes) {
                    if (isExitNodeType(n.data.nodeType)) {
                      fingerprints.current[n.id] = inputFingerprint(n.id, g.nodes, g.edges);
                    }
                  }
                  setAssetTick((n) => n + 1);
                }}
                onLocked={setAgentLocked}
                onBeforeSend={async () => {
                  const cur = JSON.stringify(toApiGraph(nodesRef.current, edgesRef.current));
                  if (cur !== lastSavedRef.current) {
                    await saveDraft({ silent: true });
                  }
                }}
              />
            ) : (
            <div className="cv-dock-scroll">
              {leftTab === "nodes" ? (
                <div className="cv-section">
                  <div className="cv-palette">
                    {PALETTE.map((p) => (
                      <button
                        key={p.type}
                        type="button"
                        className="cv-add"
                        disabled={agentLocked}
                        onClick={() => {
                          const extra: Partial<WfData> = {};
                          if (p.type === "LlmText") extra.model_id = llmModelId;
                          if (p.type === "TextToImage") extra.model_id = imageModels[0]?.model_id;
                          if (p.type === "TtsSpeak") extra.model_id = ttsModelId;
                          addNode(p.type, extra);
                        }}
                      >
                        <strong>{p.label}</strong>
                        <span>{p.hint}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : workflowId ? (
                <ProjectAssetPanel
                  workflowId={workflowId}
                  reloadKey={assetTick}
                  onPlace={(type, url, label) => {
                    if (type === "ImageAsset") {
                      addNode("ImageAsset", { image_url: url, label });
                    } else if (type === "AudioAsset") {
                      addNode("AudioAsset", { audio_url: url, label });
                    } else {
                      addNode("VideoAsset", {
                        clip_url: url,
                        result_url: url,
                        preview_url: url,
                        label,
                      });
                    }
                    setLeftTab("nodes");
                  }}
                />
              ) : (
                <p className="muted">项目尚未打开</p>
              )}
              {error && <p className="error">{error}</p>}
              {run && isActiveRun(run.status) && (
                <div className="cv-run">
                  <p>
                    <strong>{STATUS_LABEL[run.status] || run.status}</strong>
                    {run.cost > 0 && <> · {run.cost.toFixed(2)}</>}
                  </p>
                  {run.error_message && <p className="error">{run.error_message}</p>}
                </div>
              )}
            </div>
            )}
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

      {selected && (
        <div className={`cv-inspector is-open${agentLocked ? " is-locked" : ""}`}>
          <div className="cv-dock-head">
            <div>
              <p className="eyebrow">详细信息</p>
              <strong>{selected.data.label}</strong>
            </div>
            <button
              type="button"
              className="cv-panel-toggle cv-panel-close"
              aria-label="关闭详细信息"
              title="关闭"
              onClick={() => setSelectedId(null)}
            >
              关闭
            </button>
          </div>
          <div className="cv-dock-scroll">
            <WfInspector
              data={selected.data}
              models={models}
              llmModels={llmModels}
              ttsModels={ttsModels}
              imageModels={imageModels}
              modelId={modelId}
              onChange={agentLocked ? () => undefined : updateSelected}
              onGenerate={
                selectedCanGenerate && !agentLocked
                  ? () => {
                      if (!selectedId) return;
                      void startRun([selectedId], "生成选中节点");
                    }
                  : undefined
              }
              canGenerate={selectedCanGenerate && !busy && !agentLocked && !(run && isActiveRun(run.status))}
              onExpandScenes={(mode) => void expandSelectedScenes(mode)}
              canExpandScenes={
                normalizeNodeType(selected.data.nodeType) === "VideoReversePrompt" &&
                Array.isArray(selected.data.scenes) &&
                selected.data.scenes.length > 0 &&
                !busy &&
                !agentLocked
              }
              onDelete={() => {
                if (agentLocked) return;
                setNodes((ns) => ns.filter((n) => n.id !== selectedId));
                setEdges((es: Edge[]) =>
                  es.filter((e) => e.source !== selectedId && e.target !== selectedId),
                );
                setSelectedId(null);
              }}
            />
          </div>
        </div>
      )}

      {fullscreen && (
        <div className="cv-modal-backdrop" onClick={() => setFullscreen(null)}>
          <div className="cv-fullscreen" onClick={(e) => e.stopPropagation()}>
            {fullscreen.kind === "video" ? (
              <video src={fullscreen.url} controls autoPlay />
            ) : fullscreen.kind === "audio" ? (
              <audio src={fullscreen.url} controls autoPlay />
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
    </div>
  );
}
