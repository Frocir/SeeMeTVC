import type { WorkflowGraph } from "../api";
import { toApiGraph } from "./graph";
import { WF_TEMPLATES, type WfTemplateId } from "./templates";

export function graphBrand(graph?: WorkflowGraph | null): string {
  for (const n of graph?.nodes || []) {
    const data = (n.data || {}) as Record<string, unknown>;
    if (data.textRole === "brief" && typeof data.brand === "string" && data.brand.trim()) {
      return data.brand.trim();
    }
  }
  return "GlamPilot";
}

export function graphAspect(graph?: WorkflowGraph | null): string {
  for (const n of graph?.nodes || []) {
    const data = (n.data || {}) as Record<string, unknown>;
    const t = String(data.nodeType || n.type || "");
    if ((t === "VideoMux" || t === "TimelineMux") && typeof data.aspect === "string" && data.aspect) {
      return data.aspect;
    }
  }
  return "16:9";
}

export function buildTemplateGraph(
  id: WfTemplateId,
  modelId: string,
  patch?: { brand?: string; prompt?: string },
): WorkflowGraph {
  const tpl = WF_TEMPLATES.find((t) => t.id === id) || WF_TEMPLATES[0];
  const built = tpl.build(modelId);
  const nodes = built.nodes.map((n) => {
    const data = { ...n.data };
    if (data.textRole === "brief") {
      if (patch?.brand) data.brand = patch.brand;
      if (patch?.prompt) {
        data.prompt = patch.prompt;
        data.text = patch.prompt;
      }
    }
    return { ...n, data };
  });
  return toApiGraph(nodes, built.edges);
}
