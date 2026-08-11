import type { Edge, Node } from "@xyflow/react";
import { isExitNodeType, normalizeNodeType, type WfData } from "./types";

/** Fingerprint of inputs that feed an exit node (for auto-queue). */
export function inputFingerprint(nodeId: string, nodes: Node<WfData>[], edges: Edge[]): string {
  const incoming = edges.filter((e) => e.target === nodeId);
  const parts = incoming.map((e) => {
    const src = nodes.find((n) => n.id === e.source);
    const d = src?.data;
    return [
      e.source,
      e.sourceHandle || "",
      e.targetHandle || "",
      d?.prompt || "",
      d?.text || "",
      d?.image_url || "",
      d?.clip_url || "",
      d?.result_url || "",
      d?.preview_url || "",
      JSON.stringify(d?.runOutput?.clips || null),
    ].join("|");
  });
  const self = nodes.find((n) => n.id === nodeId)?.data;
  parts.push(
    [
      self?.model_id || "",
      self?.duration_seconds ?? "",
      self?.max_shots ?? "",
      self?.trim_start ?? "",
      self?.trim_end ?? "",
      self?.aspect || "",
    ].join("|"),
  );
  return parts.join("::");
}

export function exitInputsReady(nodeId: string, nodes: Node<WfData>[], edges: Edge[]): boolean {
  const node = nodes.find((n) => n.id === nodeId);
  if (!node || !isExitNodeType(node.data.nodeType)) return false;
  const nt = normalizeNodeType(node.data.nodeType);
  const incoming = edges.filter((e) => e.target === nodeId);
  if (nt === "ImageToVideo") {
    const hasPrompt =
      incoming.some((e) => (e.targetHandle || "") === "prompt") ||
      Boolean(node.data.prompt) ||
      Boolean(node.data.text);
    // image optional for t2v fallback
    return hasPrompt || incoming.length > 0;
  }
  if (nt === "VideoTrim" || nt === "VideoMux") {
    return incoming.length > 0;
  }
  return incoming.length > 0;
}

export function markDownstreamStale(
  sourceId: string,
  nodes: Node<WfData>[],
  edges: Edge[],
): Node<WfData>[] {
  const kids = new Set<string>();
  const walk = (id: string) => {
    for (const e of edges) {
      if (e.source === id && !kids.has(e.target)) {
        kids.add(e.target);
        walk(e.target);
      }
    }
  };
  walk(sourceId);
  if (!kids.size) return nodes;
  return nodes.map((n) => (kids.has(n.id) ? { ...n, data: { ...n.data, stale: true } } : n));
}

export function collectDownstreamExitIds(
  sourceId: string,
  nodes: Node<WfData>[],
  edges: Edge[],
): string[] {
  const ordered: string[] = [];
  const seen = new Set<string>();
  const walk = (id: string) => {
    for (const e of edges) {
      if (e.source !== id) continue;
      const t = e.target;
      if (seen.has(t)) continue;
      seen.add(t);
      const n = nodes.find((x) => x.id === t);
      if (n && isExitNodeType(n.data.nodeType)) ordered.push(t);
      walk(t);
    }
  };
  walk(sourceId);
  return ordered;
}
