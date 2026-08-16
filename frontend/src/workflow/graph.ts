import type { Edge, Node } from "@xyflow/react";
import { dropClosedNarrationEdges } from "./ports";
import { syncWiredData } from "./sync";
import { defaultData } from "./templates";
import { legacyLlmRole, normalizeNodeType, type WfData, type WfNodeType } from "./types";

export function toApiGraph(nodes: Node<WfData>[], edges: Edge[]) {
  return {
    nodes: nodes.map((n) => {
      const { onLabelChange: _cb, ...rest } = n.data as WfData & { onLabelChange?: unknown };
      return {
        id: n.id,
        type: n.data.nodeType,
        position: n.position,
        data: { ...rest },
      };
    }),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      ...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
      ...(e.targetHandle ? { targetHandle: e.targetHandle } : {}),
    })),
  };
}

function resolveVideoModelId(raw: unknown, preferred: string): string {
  const mid = String(raw || "").trim();
  if (!mid || mid === "seedance") return preferred || "seedance-2.5";
  return mid;
}

export function fromApiGraph(
  graph: { nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>> },
  modelId: string,
): { nodes: Node<WfData>[]; edges: Edge[] } {
  const rawNodes = graph.nodes || [];
  const nodes: Node<WfData>[] = rawNodes.map((n, i) => {
    const id = String(n.id ?? `n${i}`);
    const dataRaw = (n.data || {}) as Partial<WfData>;
    const rawType = String(n.type || "");
    const declared = String(
      dataRaw.nodeType ||
        (rawType !== "wf" && rawType !== "media" && rawType ? rawType : "") ||
        "TextAsset",
    ) as WfNodeType;
    const nodeType = normalizeNodeType(declared);
    const base = defaultData(declared, modelId);
    const rawRole = String(dataRaw.textRole || "");
    const textRole = rawRole === "script" ? "brief" : dataRaw.textRole;
    const llmRole = dataRaw.llmRole || legacyLlmRole(declared) || base.llmRole;
    return {
      id,
      type: "media",
      position: (n.position as { x: number; y: number }) || { x: 80 + i * 200, y: 120 },
      data: {
        ...base,
        ...dataRaw,
        nodeType,
        textRole: textRole || base.textRole,
        llmRole,
        label: dataRaw.label || base.label,
        model_id:
          nodeType === "ImageToVideo" || nodeType === "ShotGenerate"
            ? resolveVideoModelId(dataRaw.model_id, modelId)
            : dataRaw.model_id || base.model_id,
      },
    };
  });
  const edges: Edge[] = (graph.edges || []).map((e, i) => ({
    id: String(e.id ?? `e${i}`),
    source: String(e.source),
    target: String(e.target),
    ...(e.sourceHandle ? { sourceHandle: String(e.sourceHandle) } : {}),
    ...(e.targetHandle ? { targetHandle: String(e.targetHandle) } : {}),
  }));
  const kept = dropClosedNarrationEdges(nodes, edges);
  return { nodes: syncWiredData(nodes, kept), edges: kept };
}
