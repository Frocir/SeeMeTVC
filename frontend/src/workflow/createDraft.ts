import { useNavigate } from "react-router-dom";
import { api, type Workflow } from "../api";
import { buildTemplateGraph } from "../workflow/draftMeta";
import { WF_TEMPLATES, type WfTemplateId } from "../workflow/templates";

export async function createDraft(opts: {
  name: string;
  template: WfTemplateId | "blank";
  modelId?: string;
  brand?: string;
  prompt?: string;
}): Promise<Workflow> {
  const graph =
    opts.template === "blank"
      ? { nodes: [], edges: [] }
      : buildTemplateGraph(opts.template, opts.modelId || "seedance-2.5", {
          brand: opts.brand,
          prompt: opts.prompt,
        });
  return api<Workflow>("/api/workflows", {
    method: "POST",
    body: JSON.stringify({ name: opts.name, brand: opts.brand, graph }),
  });
}

export function useOpenDraft() {
  const navigate = useNavigate();
  return (id: number) => navigate(`/workflow/${id}`);
}

export { WF_TEMPLATES };
export type { WfTemplateId };
