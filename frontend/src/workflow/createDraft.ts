import { useNavigate } from "react-router-dom";
import { api, type Workflow } from "../api";
import { buildTemplateGraph } from "../workflow/draftMeta";
import { WF_TEMPLATES, type WfTemplateId } from "../workflow/templates";

export async function createDraft(opts: {
  name: string;
  template: WfTemplateId;
  modelId?: string;
  brand?: string;
  prompt?: string;
}): Promise<Workflow> {
  const graph = buildTemplateGraph(opts.template, opts.modelId || "", {
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
