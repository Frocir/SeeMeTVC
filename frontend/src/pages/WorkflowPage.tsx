import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  api,
  isActiveRun,
  isTerminalRun,
  STATUS_LABEL,
  type ModelOption,
  type Workflow,
  type WorkflowRun,
} from "../api";
import { useAuth } from "../auth";
import ReferenceImageField from "../components/ReferenceImageField";
import { ensureUpstreamImageUrl } from "../imageUrl";

export type WfNodeType =
  | "BriefInput"
  | "ScenePlan"
  | "ShotGenerate"
  | "MakeupControl"
  | "TimelineMux"
  | "PreviewOut";

type WfData = {
  nodeType: WfNodeType;
  label: string;
  brand?: string;
  selling_points?: string;
  slogan?: string;
  prompt?: string;
  image_url?: string;
  scene_count?: number;
  model_id?: string;
  duration_seconds?: number;
  use_scenes?: boolean;
  max_shots?: number;
  intensity?: number;
  before_prompt?: string;
  after_prompt?: string;
  aspect?: string;
  pick?: string;
  runStatus?: string;
  runError?: string;
};

const PALETTE: { type: WfNodeType; label: string; hint: string }[] = [
  { type: "BriefInput", label: "Brief 输入", hint: "品牌 / 卖点 / slogan" },
  { type: "ScenePlan", label: "场景分镜", hint: "拆多场景" },
  { type: "MakeupControl", label: "妆容控制", hint: "妆前妆后强度" },
  { type: "ShotGenerate", label: "镜头生成", hint: "调渠道出片" },
  { type: "TimelineMux", label: "时间线拼接", hint: "16:9 / 9:16" },
  { type: "PreviewOut", label: "成片预览", hint: "预览与下载" },
];

function defaultData(type: WfNodeType, modelId = ""): WfData {
  const label = PALETTE.find((p) => p.type === type)?.label || type;
  switch (type) {
    case "BriefInput":
      return {
        nodeType: type,
        label,
        brand: "SeeMe",
        selling_points: "水光肌、持妆、气色",
        slogan: "看见更好的自己",
        prompt: "高端美妆广告短片，柔光特写",
      };
    case "ScenePlan":
      return { nodeType: type, label, scene_count: 3 };
    case "ShotGenerate":
      return {
        nodeType: type,
        label,
        model_id: modelId,
        duration_seconds: 5,
        use_scenes: true,
        max_shots: 3,
      };
    case "MakeupControl":
      return {
        nodeType: type,
        label,
        intensity: 0.7,
        before_prompt: "素颜自然肤质",
        after_prompt: "精致妆容，气色明亮",
      };
    case "TimelineMux":
      return { nodeType: type, label, aspect: "16:9", pick: "first" };
    case "PreviewOut":
      return { nodeType: type, label };
  }
}

function defaultGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  const nodes: Node<WfData>[] = [
    {
      id: "brief",
      type: "wf",
      position: { x: 40, y: 120 },
      data: defaultData("BriefInput", modelId),
    },
    {
      id: "scenes",
      type: "wf",
      position: { x: 300, y: 40 },
      data: defaultData("ScenePlan", modelId),
    },
    {
      id: "makeup",
      type: "wf",
      position: { x: 300, y: 260 },
      data: defaultData("MakeupControl", modelId),
    },
    {
      id: "shot",
      type: "wf",
      position: { x: 560, y: 120 },
      data: defaultData("ShotGenerate", modelId),
    },
    {
      id: "mux",
      type: "wf",
      position: { x: 820, y: 120 },
      data: defaultData("TimelineMux", modelId),
    },
    {
      id: "preview",
      type: "wf",
      position: { x: 1080, y: 120 },
      data: defaultData("PreviewOut", modelId),
    },
  ];
  const edges: Edge[] = [
    { id: "e1", source: "brief", target: "scenes" },
    { id: "e2", source: "brief", target: "makeup" },
    { id: "e3", source: "scenes", target: "shot" },
    { id: "e4", source: "makeup", target: "shot" },
    { id: "e5", source: "shot", target: "mux" },
    { id: "e6", source: "mux", target: "preview" },
  ];
  return { nodes, edges };
}

function WfNode({ data, selected }: NodeProps<Node<WfData>>) {
  const st = data.runStatus;
  return (
    <div className={`wf-node ${selected ? "selected" : ""} ${st ? `st-${st}` : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="wf-node-type">{data.nodeType}</div>
      <div className="wf-node-title">{data.label}</div>
      {st && <div className="wf-node-status">{STATUS_LABEL[st] || st}</div>}
      {data.runError && <div className="wf-node-err">{data.runError}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { wf: WfNode };

function toApiGraph(nodes: Node<WfData>[], edges: Edge[]) {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.nodeType,
      position: n.position,
      data: { ...n.data },
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
    })),
  };
}

function fromApiGraph(
  graph: { nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>> },
  modelId: string,
): { nodes: Node<WfData>[]; edges: Edge[] } {
  const rawNodes = graph.nodes || [];
  const nodes: Node<WfData>[] = rawNodes.map((n, i) => {
    const id = String(n.id ?? `n${i}`);
    const dataRaw = (n.data || {}) as Partial<WfData>;
    const nodeType = (String(n.type || dataRaw.nodeType || "BriefInput") as WfNodeType);
    const base = defaultData(nodeType, modelId);
    return {
      id,
      type: "wf",
      position: (n.position as { x: number; y: number }) || { x: 80 + i * 200, y: 120 },
      data: { ...base, ...dataRaw, nodeType, label: dataRaw.label || base.label },
    };
  });
  const edges: Edge[] = (graph.edges || []).map((e, i) => ({
    id: String(e.id ?? `e${i}`),
    source: String(e.source),
    target: String(e.target),
  }));
  return { nodes, edges };
}

export default function WorkflowPage() {
  const { refresh } = useAuth();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [name, setName] = useState("美妆 TVC 工作流");
  const [workflowId, setWorkflowId] = useState<number | null>(null);
  const [savedList, setSavedList] = useState<Workflow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const idSeq = useRef(1);

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
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = useMemo(
    () => nodes.find((n) => n.id === selectedId) ?? null,
    [nodes, selectedId],
  );

  const onConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge({ ...c, id: `e-${Date.now()}` }, eds)),
    [setEdges],
  );

  function addNode(type: WfNodeType) {
    const id = `n${Date.now()}-${idSeq.current++}`;
    setNodes((ns) => [
      ...ns,
      {
        id,
        type: "wf",
        position: { x: 120 + (ns.length % 4) * 40, y: 80 + (ns.length % 3) * 40 },
        data: defaultData(type, modelId),
      },
    ]);
    setSelectedId(id);
  }

  function updateSelected(patch: Partial<WfData>) {
    if (!selectedId) return;
    setNodes((ns) =>
      ns.map((n) => (n.id === selectedId ? { ...n, data: { ...n.data, ...patch } } : n)),
    );
  }

  function applyRunStates(r: WorkflowRun) {
    setNodes((ns) =>
      ns.map((n) => {
        const st = r.node_states?.[n.id];
        if (!st) return { ...n, data: { ...n.data, runStatus: undefined, runError: undefined } };
        return {
          ...n,
          data: {
            ...n.data,
            runStatus: st.status,
            runError: st.error || undefined,
          },
        };
      }),
    );
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
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }

  async function runGraph() {
    setBusy(true);
    setError("");
    try {
      const graph = toApiGraph(nodes, edges);
      const patchedNodes: typeof graph.nodes = [];
      for (const n of graph.nodes) {
        const d = { ...(n.data as WfData) };
        if (d.nodeType === "ShotGenerate" && !d.model_id) {
          d.model_id = modelId;
        }
        if (d.image_url) {
          d.image_url = (await ensureUpstreamImageUrl(d.image_url)) || undefined;
        }
        patchedNodes.push({ ...n, data: d });
      }
      // Reflect re-uploaded URLs back onto the canvas
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
      const patched = { ...graph, nodes: patchedNodes };
      const r = await api<WorkflowRun>("/api/workflows/runs", {
        method: "POST",
        body: JSON.stringify({
          workflow_id: workflowId,
          graph: patched,
          name,
        }),
      });
      setRun(r);
      applyRunStates(r);
      if (r.workflow_id) setWorkflowId(r.workflow_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "执行失败");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!run || !isActiveRun(run.status)) return;
    const t = setInterval(() => {
      void api<WorkflowRun>(`/api/workflows/runs/${run.id}`)
        .then(async (fresh) => {
          setRun(fresh);
          applyRunStates(fresh);
          if (isTerminalRun(fresh.status)) {
            await refresh();
          }
        })
        .catch(() => null);
    }, 2000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, run?.status, refresh]);

  const d = selected?.data;

  return (
    <div className="wf-stage">
      <aside className="wf-rail">
        <p className="eyebrow">节点工作流</p>
        <h1>美妆 TVC DAG</h1>
        <p className="lead">像 ComfyUI 一样编排 Brief → 分镜 → 妆容 → 生成 → 拼接 → 预览。</p>

        <label>
          工作流名称
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>

        <div className="wf-palette">
          {PALETTE.map((p) => (
            <button key={p.type} type="button" className="wf-palette-btn" onClick={() => addNode(p.type)}>
              <strong>{p.label}</strong>
              <span>{p.hint}</span>
            </button>
          ))}
        </div>

        <div className="wf-actions">
          <button type="button" className="primary" disabled={busy} onClick={() => void saveDraft()}>
            保存草稿
          </button>
          <button type="button" className="primary solid" disabled={busy || !modelId} onClick={() => void runGraph()}>
            执行工作流
          </button>
        </div>

        {savedList.length > 0 && (
          <div className="wf-saved">
            <p className="eyebrow">已保存</p>
            {savedList.slice(0, 8).map((w) => (
              <button key={w.id} type="button" className="ghost block" onClick={() => void loadWorkflow(w.id)}>
                {w.name} <em>#{w.id}</em>
              </button>
            ))}
          </div>
        )}

        {error && <p className="error">{error}</p>}

        {run && (
          <div className="wf-run-panel">
            <p className="eyebrow">运行 #{run.id}</p>
            <p>
              状态 <strong>{STATUS_LABEL[run.status] || run.status}</strong>
              {run.cost > 0 && <> · 费用 {run.cost.toFixed(2)}</>}
            </p>
            {run.error_message && <p className="error">{run.error_message}</p>}
            {run.result_url && (
              <video className="wf-preview-video" src={run.result_url} controls playsInline />
            )}
          </div>
        )}
      </aside>

      <section className="wf-canvas-wrap">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => setSelectedId(n.id)}
          onPaneClick={() => setSelectedId(null)}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} color="rgba(212,87,138,0.12)" />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </section>

      <aside className="wf-inspector">
        <p className="eyebrow">节点属性</p>
        {!d ? (
          <p className="muted">选中画布上的节点以编辑参数。</p>
        ) : (
          <div className="wf-fields">
            <h2>{d.label}</h2>
            <p className="muted mono">{d.nodeType}</p>

            {d.nodeType === "BriefInput" && (
              <>
                <label>
                  品牌
                  <input value={d.brand || ""} onChange={(e) => updateSelected({ brand: e.target.value })} />
                </label>
                <label>
                  卖点
                  <input
                    value={d.selling_points || ""}
                    onChange={(e) => updateSelected({ selling_points: e.target.value })}
                  />
                </label>
                <label>
                  Slogan
                  <input value={d.slogan || ""} onChange={(e) => updateSelected({ slogan: e.target.value })} />
                </label>
                <label>
                  补充提示
                  <textarea
                    rows={3}
                    value={d.prompt || ""}
                    onChange={(e) => updateSelected({ prompt: e.target.value })}
                  />
                </label>
                <ReferenceImageField
                  value={d.image_url || ""}
                  onChange={(url) => updateSelected({ image_url: url })}
                  label="参考图"
                  hint="本地上传或粘贴 URL"
                />
              </>
            )}

            {d.nodeType === "ScenePlan" && (
              <label>
                场景数量
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={d.scene_count ?? 3}
                  onChange={(e) => updateSelected({ scene_count: Number(e.target.value) })}
                />
              </label>
            )}

            {d.nodeType === "MakeupControl" && (
              <>
                <label>
                  妆容强度 {Math.round((d.intensity ?? 0.7) * 100)}%
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={d.intensity ?? 0.7}
                    onChange={(e) => updateSelected({ intensity: Number(e.target.value) })}
                  />
                </label>
                <label>
                  妆前描述
                  <input
                    value={d.before_prompt || ""}
                    onChange={(e) => updateSelected({ before_prompt: e.target.value })}
                  />
                </label>
                <label>
                  妆后描述
                  <input
                    value={d.after_prompt || ""}
                    onChange={(e) => updateSelected({ after_prompt: e.target.value })}
                  />
                </label>
              </>
            )}

            {d.nodeType === "ShotGenerate" && (
              <>
                <label>
                  模型
                  <select
                    value={d.model_id || modelId}
                    onChange={(e) => updateSelected({ model_id: e.target.value })}
                  >
                    {models.map((m) => (
                      <option key={m.model_id} value={m.model_id}>
                        {m.model_id} · {m.cost_per_second}/s
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  时长（秒）
                  <input
                    type="number"
                    min={2}
                    max={30}
                    value={d.duration_seconds ?? 5}
                    onChange={(e) => updateSelected({ duration_seconds: Number(e.target.value) })}
                  />
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={d.use_scenes !== false}
                    onChange={(e) => updateSelected({ use_scenes: e.target.checked })}
                  />
                  使用上游分镜场景
                </label>
                <label>
                  最多生成镜头数
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={d.max_shots ?? 3}
                    onChange={(e) => updateSelected({ max_shots: Number(e.target.value) })}
                  />
                </label>
              </>
            )}

            {d.nodeType === "TimelineMux" && (
              <>
                <label>
                  画幅
                  <select
                    value={d.aspect || "16:9"}
                    onChange={(e) => updateSelected({ aspect: e.target.value })}
                  >
                    <option value="16:9">16:9</option>
                    <option value="9:16">9:16</option>
                  </select>
                </label>
                <label>
                  主预览片段
                  <select value={d.pick || "first"} onChange={(e) => updateSelected({ pick: e.target.value })}>
                    <option value="first">第一镜</option>
                    <option value="last">最后一镜</option>
                  </select>
                </label>
              </>
            )}

            {d.nodeType === "PreviewOut" && (
              <p className="muted">执行后在此节点汇总成片预览地址。</p>
            )}

            <button
              type="button"
              className="ghost danger"
              onClick={() => {
                setNodes((ns) => ns.filter((n) => n.id !== selectedId));
                setEdges((es) => es.filter((e) => e.source !== selectedId && e.target !== selectedId));
                setSelectedId(null);
              }}
            >
              删除节点
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}
