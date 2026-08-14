import type { Node } from "@xyflow/react";
import { normalizeNodeType, type WfData } from "./types";

export type NodePortSpec = {
  id: string;
  kind: string;
  required?: string;
  fields?: string[];
  missing?: string;
  source_fields?: Record<string, string[]>;
  source_fields_missing?: string;
};

export type NodeSpec = {
  group?: string;
  label?: string;
  exit?: boolean;
  orphan?: string;
  channel?: string | null;
  run_tool?: string | null;
  fields?: string[];
  in_chain_fields?: string[];
  in_chain_missing?: string;
  inputs?: NodePortSpec[];
  outputs?: NodePortSpec[];
};

export type ForbidEdge = {
  source_type: string;
  target_type: string;
  target_handle?: string;
  source_fed_by?: string;
  message?: string;
};

export type NodeContracts = {
  kind_compat?: Record<string, string[]>;
  forbid_edges?: ForbidEdge[];
  connect_defaults?: { source_kind?: string; prefer_target?: string[] }[];
  no_default_target_handles?: string[];
  nodes?: Record<string, NodeSpec>;
};

type EdgeRef = {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

function specOf(contracts: NodeContracts, t: string): NodeSpec {
  const nt = normalizeNodeType(t as WfData["nodeType"]);
  return contracts.nodes?.[nt] || {};
}

function isExit(contracts: NodeContracts, t: string): boolean {
  return Boolean(specOf(contracts, t).exit);
}

function isProducer(contracts: NodeContracts, t: string): boolean {
  const s = specOf(contracts, t);
  if (s.orphan === "full_run_forbid") return true;
  if (s.exit || s.run_tool) return true;
  return s.group === "produce" || s.group === "finish";
}

function filled(data: Record<string, unknown> | undefined, keys?: string[]): boolean {
  return (keys || []).some((k) => typeof data?.[k] === "string" && String(data[k]).trim().length > 0);
}

function incoming(id: string, edges: EdgeRef[]): EdgeRef[] {
  return edges.filter((e) => e.target === id);
}

function incomingHandles(id: string, edges: EdgeRef[]): Set<string> {
  const found = new Set<string>();
  for (const e of incoming(id, edges)) {
    const h = String(e.targetHandle || e.sourceHandle || "");
    if (h) found.add(h);
  }
  return found;
}

function adj(ids: Set<string>, edges: EdgeRef[]): { down: Map<string, string[]>; up: Map<string, string[]> } {
  const down = new Map<string, string[]>();
  const up = new Map<string, string[]>();
  for (const id of ids) {
    down.set(id, []);
    up.set(id, []);
  }
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    down.get(e.source)?.push(e.target);
    up.get(e.target)?.push(e.source);
  }
  return { down, up };
}

function hasCycle(ids: string[], down: Map<string, string[]>): boolean {
  const indeg = new Map(ids.map((id) => [id, 0]));
  for (const [src, outs] of down) {
    if (!indeg.has(src)) continue;
    for (const tgt of outs) {
      if (indeg.has(tgt)) indeg.set(tgt, (indeg.get(tgt) || 0) + 1);
    }
  }
  const q = ids.filter((id) => (indeg.get(id) || 0) === 0);
  let seen = 0;
  while (q.length) {
    const u = q.pop() as string;
    seen += 1;
    for (const v of down.get(u) || []) {
      if (!indeg.has(v)) continue;
      const next = (indeg.get(v) || 0) - 1;
      indeg.set(v, next);
      if (next === 0) q.push(v);
    }
  }
  return seen !== ids.length;
}

function undirectedComponents(ids: string[], edges: EdgeRef[]): string[][] {
  const parent = new Map(ids.map((id) => [id, id]));
  const find = (x: string): string => {
    let cur = x;
    while (parent.get(cur) !== cur) {
      const p = parent.get(cur) as string;
      parent.set(cur, parent.get(p) as string);
      cur = parent.get(cur) as string;
    }
    return cur;
  };
  const union = (a: string, b: string) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent.set(rb, ra);
  };
  const idSet = new Set(ids);
  for (const e of edges) {
    if (idSet.has(e.source) && idSet.has(e.target)) union(e.source, e.target);
  }
  const groups = new Map<string, string[]>();
  for (const id of ids) {
    const r = find(id);
    const bag = groups.get(r) || [];
    bag.push(id);
    groups.set(r, bag);
  }
  return [...groups.values()];
}

function canReach(start: string, goals: Set<string>, down: Map<string, string[]>): boolean {
  if (goals.has(start)) return true;
  const seen = new Set([start]);
  const stack = [start];
  while (stack.length) {
    const u = stack.pop() as string;
    for (const v of down.get(u) || []) {
      if (seen.has(v)) continue;
      if (goals.has(v)) return true;
      seen.add(v);
      stack.push(v);
    }
  }
  return false;
}

function fmt(template: string, label: string, missing = ""): string {
  return template.replaceAll("{label}", label).replaceAll("{missing}", missing);
}

function ttsFed(sourceId: string, sourceType: string, edges: EdgeRef[], byId: Map<string, Node<WfData>>): boolean {
  if (sourceType === "TtsSpeak") return true;
  if (sourceType !== "AudioTrim") return false;
  return edges.some((e) => {
    if (e.target !== sourceId) return false;
    const grand = byId.get(e.source);
    return grand ? normalizeNodeType(grand.data.nodeType) === "TtsSpeak" : false;
  });
}

function nodeInputReason(
  node: Node<WfData>,
  edges: EdgeRef[],
  byId: Map<string, Node<WfData>>,
  contracts: NodeContracts,
): string | null {
  const nt = normalizeNodeType(node.data.nodeType);
  const spec = specOf(contracts, nt);
  const label = node.data.label || spec.label || nt;
  const inc = incoming(node.id, edges);
  const handles = incomingHandles(node.id, edges);
  const d = node.data as unknown as Record<string, unknown>;

  if (spec.in_chain_fields?.length && !filled(d, spec.in_chain_fields) && !inc.length) {
    return fmt(spec.in_chain_missing || "「{label}」缺少必要素材。", label);
  }

  const missingEdges: string[] = [];
  let edgeTmpl = "";
  for (const port of spec.inputs || []) {
    const mode = port.required || "optional";
    if (mode === "optional") continue;
    const hasEdge = handles.has(port.id) || (!port.id && inc.length > 0);
    const hasFields = filled(d, port.fields || spec.fields);
    if (mode === "edge") {
      if (!hasEdge) {
        missingEdges.push(port.id);
        edgeTmpl = port.missing || edgeTmpl || "「{label}」缺少输入：{missing}。";
      }
      if (hasEdge && port.source_fields) {
        for (const e of inc) {
          const th = String(e.targetHandle || "");
          if (th && th !== port.id) continue;
          const src = byId.get(e.source);
          if (!src) continue;
          const st = normalizeNodeType(src.data.nodeType);
          const need = port.source_fields[st];
          if (!need) continue;
          if (!filled(src.data as unknown as Record<string, unknown>, need)) {
            return port.source_fields_missing || `「${label}」的 ${port.id} 口所接节点缺少文件。`;
          }
        }
      }
      continue;
    }
    if (mode === "edge_or_fields" && !hasEdge && !hasFields) {
      return fmt(port.missing || "「{label}」缺少输入。", label);
    }
    if (mode === "fields" && !hasFields) {
      return fmt(port.missing || "「{label}」缺少输入。", label);
    }
  }
  if (missingEdges.length) return fmt(edgeTmpl, label, missingEdges.join("、"));
  return null;
}

function forbidReason(
  edges: EdgeRef[],
  byId: Map<string, Node<WfData>>,
  check: Set<string>,
  contracts: NodeContracts,
): string | null {
  for (const e of edges) {
    if (!check.has(e.target)) continue;
    const src = byId.get(e.source);
    const tgt = byId.get(e.target);
    if (!src || !tgt) continue;
    const st = normalizeNodeType(src.data.nodeType);
    const tt = normalizeNodeType(tgt.data.nodeType);
    const th = String(e.targetHandle || "");
    for (const rule of contracts.forbid_edges || []) {
      if (rule.target_type !== tt) continue;
      if (rule.target_handle && rule.target_handle !== th) continue;
      if (rule.source_type !== st) continue;
      if (rule.source_fed_by && !ttsFed(src.id, st, edges, byId)) continue;
      return rule.message || "非法连线";
    }
  }
  return null;
}

function portKind(spec: NodeSpec, which: "inputs" | "outputs", handle?: string | null): string {
  const h = String(handle || "");
  if (!h) return "";
  const ports = which === "inputs" ? spec.inputs || [] : spec.outputs || [];
  return ports.find((p) => p.id === h)?.kind || h;
}

export function kindsCompatible(contracts: NodeContracts | null | undefined, sh?: string | null, th?: string | null): boolean {
  if (!sh || !th) return true;
  if (sh === th) return true;
  return (contracts?.kind_compat?.[sh] || []).includes(th);
}

function invalidEdgeReason(
  edges: EdgeRef[],
  byId: Map<string, Node<WfData>>,
  check: Set<string>,
  contracts: NodeContracts,
): string | null {
  for (const e of edges) {
    if (!check.has(e.target)) continue;
    const src = byId.get(e.source);
    const tgt = byId.get(e.target);
    if (!src || !tgt) return "画布存在指向已删除节点的连线，请删除无效连线后再运行。";
    const st = normalizeNodeType(src.data.nodeType);
    const tt = normalizeNodeType(tgt.data.nodeType);
    const srcSpec = specOf(contracts, st);
    const tgtSpec = specOf(contracts, tt);
    const sh = String(e.sourceHandle || "");
    const th = String(e.targetHandle || "");
    const outs = (srcSpec.outputs || []).map((p) => p.id);
    const ins = (tgtSpec.inputs || []).map((p) => p.id);
    if (outs.length && !outs.includes(sh)) {
      return `「${srcSpec.label || st}」没有输出端口 ${sh || "—"}。可用：${outs.join("、")}。`;
    }
    if (ins.length && !ins.includes(th)) {
      return `「${tgtSpec.label || tt}」没有输入端口 ${th || "—"}。可用：${ins.join("、")}。`;
    }
    const sourceKind = portKind(srcSpec, "outputs", sh);
    const targetKind = portKind(tgtSpec, "inputs", th);
    if (sourceKind && targetKind && !kindsCompatible(contracts, sourceKind, targetKind)) {
      return `端口不兼容：${st}.${sh}(${sourceKind}) 不能接到 ${tt}.${th}(${targetKind})。`;
    }
  }
  return null;
}

export function cannotRunReason(
  nodes: Node<WfData>[],
  edges: EdgeRef[] = [],
  opts: {
    modelId?: string;
    llmReady?: boolean;
    ttsReady?: boolean;
    imageReady?: boolean;
    targetIds?: string[];
    contracts?: NodeContracts | null;
  } = {},
): string | null {
  const contracts = opts.contracts;
  if (!contracts?.nodes) {
    return "节点规约未加载，请刷新页面。";
  }
  if (!nodes.length) {
    return "画布上没有节点，无法生成。请从左侧「节点」添加「图生视频」等节点后再一键跑。";
  }
  const targets = opts.targetIds?.filter(Boolean) || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const ids = nodes.map((n) => n.id);
  const fullRun = !targets.length;
  if (targets.length) {
    if (targets.some((id) => !byId.has(id))) {
      return "选中的节点已不在画布上，无法生成。";
    }
  } else if (!nodes.some((n) => isExit(contracts, n.data.nodeType))) {
    const extras = nodes
      .filter((n) => specOf(contracts, n.data.nodeType).orphan === "full_run_forbid")
      .map((n) => n.data.label || n.id);
    if (extras.length) {
      return (
        `没有可出片的节点，无法一键跑。画布上的「${extras.slice(0, 3).join("、")}」需要接到「图生视频」「文生图」「混音」或「字幕」，` +
        "或选中该节点单独点「生成」。"
      );
    }
    return "没有可出片的节点。请添加「图生视频」「文生图」「混音」或「字幕」后再一键跑。";
  }

  const { down, up } = adj(new Set(ids), edges);
  if (hasCycle(ids, down)) {
    return "节点图存在环或无效依赖，无法执行。";
  }

  if (fullRun) {
    const islands = undirectedComponents(ids, edges).filter((comp) =>
      comp.some((id) => {
        const n = byId.get(id);
        return n ? isProducer(contracts, n.data.nodeType) : false;
      }),
    );
    if (islands.length > 1) {
      const names = islands.slice(0, 4).map((comp) => {
        const pick =
          comp.find((id) => {
            const n = byId.get(id);
            return n && isExit(contracts, n.data.nodeType);
          }) ||
          comp.find((id) => {
            const n = byId.get(id);
            return n && isProducer(contracts, n.data.nodeType);
          }) ||
          comp[0];
        const n = byId.get(pick);
        return `「${n?.data.label || pick}」`;
      });
      const extra = islands.length > 4 ? " 等" : "";
      return `画布上有 ${islands.length} 条互不相连的工作流（${names.join("、")}${extra}）。一键跑只能跑一条完整链路，请删掉多余节点或把它们连起来。`;
    }
    const exits = new Set(nodes.filter((n) => isExit(contracts, n.data.nodeType)).map((n) => n.id));
    for (const n of nodes) {
      if (specOf(contracts, n.data.nodeType).orphan !== "full_run_forbid") continue;
      if (isExit(contracts, n.data.nodeType)) continue;
      if (!canReach(n.id, exits, down)) {
        return `「${n.data.label || n.id}」没有连接到任何出片节点，工作流不完整。请把它接到「图生视频」等节点，或删掉后再一键跑。`;
      }
    }
  }

  if (targets.length) {
    const blocked = nodes.find((n) => targets.includes(n.id) && upstreamFailed(n.id, nodes, edges, contracts));
    if (blocked) {
      return `「${blocked.data.label || blocked.id}」的上游生产节点已失败，请先重跑上游，或点「一键跑」整链重试。`;
    }
  }

  let checkNodes: Node<WfData>[];
  if (targets.length) {
    checkNodes = nodes.filter((n) => targets.includes(n.id));
  } else {
    const exits = nodes.filter((n) => isExit(contracts, n.data.nodeType)).map((n) => n.id);
    const relevant = new Set(exits);
    const stack = [...exits];
    while (stack.length) {
      const u = stack.pop() as string;
      for (const p of up.get(u) || []) {
        if (!relevant.has(p)) {
          relevant.add(p);
          stack.push(p);
        }
      }
    }
    checkNodes = nodes.filter((n) => relevant.has(n.id));
  }
  const checkSet = new Set(checkNodes.map((n) => n.id));
  const invalidEdge = invalidEdgeReason(edges, byId, checkSet, contracts);
  if (invalidEdge) return invalidEdge;

  for (const n of checkNodes) {
    const reason = nodeInputReason(n, edges, byId, contracts);
    if (reason) return reason;
  }
  const forbid = forbidReason(edges, byId, checkSet, contracts);
  if (forbid) return forbid;

  const pool = targets.length ? nodes.filter((n) => targets.includes(n.id)) : nodes;
  const msgs: Record<string, string> = {
    video: "暂无可用视频模型，无法图生视频。请超管启用渠道后再一键跑。",
    llm: "暂无可用 LLM 渠道。请超管启用「本地 LLM 模拟」，或填写真模型 Key 后再一键跑。",
    tts: "暂无可用 TTS 渠道。请确认 aisrv 已启动，且超管已启用 Edge TTS 渠道。",
    image: "暂无可用文生图渠道。请超管启用「本地文生图模拟」后再一键跑。",
  };
  for (const n of pool) {
    const ch = specOf(contracts, n.data.nodeType).channel;
    if (ch === "video" && !(opts.modelId || "").trim()) return msgs.video;
    if (ch === "llm" && opts.llmReady === false) return msgs.llm;
    if (ch === "tts" && opts.ttsReady === false) return msgs.tts;
    if (ch === "image" && opts.imageReady === false) return msgs.image;
  }
  return null;
}

function upstreamFailed(
  nodeId: string,
  nodes: Node<WfData>[],
  edges: EdgeRef[],
  contracts: NodeContracts,
): boolean {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const seen = new Set<string>();
  const stack = [nodeId];
  while (stack.length) {
    const id = stack.pop() as string;
    for (const e of edges) {
      if (e.target !== id) continue;
      if (seen.has(e.source)) continue;
      seen.add(e.source);
      const src = byId.get(e.source);
      if (!src) continue;
      if (isProducer(contracts, src.data.nodeType) && src.data.runStatus === "failed") return true;
      stack.push(e.source);
    }
  }
  return false;
}
