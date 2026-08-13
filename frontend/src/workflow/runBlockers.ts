import type { Node } from "@xyflow/react";
import { isExitNodeType, normalizeNodeType, type WfData } from "./types";

/** Why 一键跑 / 生成 cannot start. Null means the request may proceed. */
export function cannotRunReason(
  nodes: Node<WfData>[],
  opts: { modelId?: string; targetIds?: string[] } = {},
): string | null {
  if (!nodes.length) {
    return "画布上没有节点，无法生成。请从左侧「节点」添加「图生视频」等节点，或用模板预填后再一键跑。";
  }
  const targets = opts.targetIds?.filter(Boolean) || [];
  if (targets.length) {
    const ids = new Set(nodes.map((n) => n.id));
    if (targets.some((id) => !ids.has(id))) {
      return "选中的节点已不在画布上，无法生成。";
    }
    const pool = nodes.filter((n) => targets.includes(n.id));
    const needsModel = pool.some((n) => normalizeNodeType(n.data.nodeType) === "ImageToVideo");
    if (needsModel && !(opts.modelId || "").trim()) {
      return "暂无可用模型，无法图生视频。请超管启用渠道后再一键跑。";
    }
    return null;
  }
  const runnable = nodes.filter((n) => {
    const t = normalizeNodeType(n.data.nodeType);
    return isExitNodeType(n.data.nodeType) || t === "VideoAsset";
  });
  if (!runnable.length) {
    return "没有可出片的节点。请添加「图生视频」「裁时长」或「真拼接」后再一键跑。";
  }
  const needsModel = runnable.some((n) => normalizeNodeType(n.data.nodeType) === "ImageToVideo");
  if (needsModel && !(opts.modelId || "").trim()) {
    return "暂无可用模型，无法图生视频。请超管启用渠道后再一键跑。";
  }
  return null;
}
