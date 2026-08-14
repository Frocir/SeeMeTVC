import type { Connection, Edge, Node } from "@xyflow/react";
import type { NodeContracts } from "./nodeContracts";
import { isValidPortConnection, portsFor } from "./ports";
import { normalizeNodeType, type WfData, type WfNodeType } from "./types";

/** Read the payload a source handle should send. */
export function readSourcePort(data: WfData, handle?: string | null): Partial<WfData> {
  const h = handle || "text";
  const out = data.runOutput || {};
  if (h === "narration") {
    const n = String(out.narration ?? data.narration ?? "").trim();
    return n ? { text: n, narration: n } : {};
  }
  if (h === "image" || h === "frames") {
    const frames = Array.isArray(out.frames) ? out.frames : Array.isArray(data.frames) ? data.frames : [];
    const url = String(out.image_url ?? data.image_url ?? frames[0] ?? "").trim();
    return url ? { image_url: url } : {};
  }
  if (h === "video" || h === "clips" || h === "result") {
    const url = String(
      out.result_url ?? out.clip_url ?? data.result_url ?? data.clip_url ?? data.preview_url ?? "",
    ).trim();
    return url ? { clip_url: url, result_url: url, preview_url: url } : {};
  }
  if (h === "audio" || h === "bgm" || h === "vo") {
    const url = String(out.audio_url ?? data.audio_url ?? "").trim();
    return url ? { audio_url: url } : {};
  }
  if (h === "scenes" || h === "timeline") {
    const val = out[h] ?? data[h];
    const text = typeof val === "string" ? val : val == null ? "" : JSON.stringify(val, null, 2);
    const trimmed = text.trim();
    return trimmed ? { text: trimmed, prompt: trimmed } : {};
  }
  const prompt = String(out.prompt ?? data.prompt ?? "").trim();
  const text = String(out.text ?? data.text ?? prompt).trim();
  const patch: Partial<WfData> = {};
  if (prompt) patch.prompt = prompt;
  if (text) patch.text = text;
  if (data.brand) patch.brand = data.brand;
  if (data.slogan) patch.slogan = data.slogan;
  if (data.selling_points) patch.selling_points = data.selling_points;
  return patch;
}

/** Map an incoming payload onto the target handle's fields. */
export function writeTargetPort(
  targetType: WfNodeType,
  handle: string | null | undefined,
  incoming: Partial<WfData>,
): Partial<WfData> {
  const th = handle || "";
  const nt = normalizeNodeType(targetType);
  if (th === "image") {
    return incoming.image_url ? { image_url: incoming.image_url } : {};
  }
  if (th === "video" || th === "clips") {
    const url = incoming.clip_url || incoming.result_url || incoming.preview_url;
    if (!url) return {};
    if (nt === "MixAudio") return { clip_url: url, preview_url: url };
    return { clip_url: url, result_url: url, preview_url: url };
  }
  if (th === "audio" || th === "bgm" || th === "vo") {
    return incoming.audio_url ? { audio_url: incoming.audio_url } : {};
  }
  if (th === "prompt") {
    const p = incoming.prompt || incoming.text;
    return p ? { prompt: p, text: incoming.text || p } : {};
  }
  if (th === "text") {
    const patch: Partial<WfData> = {};
    const t = incoming.narration || incoming.text || incoming.prompt;
    if (incoming.narration) {
      patch.narration = incoming.narration;
      patch.text = incoming.narration;
    } else if (t) {
      patch.text = t;
      patch.prompt = incoming.prompt || t;
    }
    if (incoming.slogan) patch.slogan = incoming.slogan;
    if (incoming.brand) patch.brand = incoming.brand;
    if (incoming.selling_points) patch.selling_points = incoming.selling_points;
    return patch;
  }
  return {};
}

function applyDefined(data: WfData, patch: Partial<WfData>): WfData {
  let dirty = false;
  const next = { ...data };
  (Object.entries(patch) as [keyof WfData, WfData[keyof WfData]][]).forEach(([key, value]) => {
    if (value === undefined || value === "") return;
    if (data[key] !== value) {
      (next as Record<string, unknown>)[key] = value;
      dirty = true;
    }
  });
  return dirty ? next : data;
}

function topoIds(nodes: Node<WfData>[], edges: Edge[]): string[] {
  const ids = nodes.map((n) => n.id);
  const indeg = new Map(ids.map((id) => [id, 0]));
  for (const e of edges) {
    if (!indeg.has(e.target)) continue;
    indeg.set(e.target, (indeg.get(e.target) || 0) + 1);
  }
  const queue = ids.filter((id) => (indeg.get(id) || 0) === 0);
  const ordered: string[] = [];
  while (queue.length) {
    const id = queue.shift() as string;
    ordered.push(id);
    for (const e of edges) {
      if (e.source !== id || !indeg.has(e.target)) continue;
      const n = (indeg.get(e.target) || 0) - 1;
      indeg.set(e.target, n);
      if (n === 0) queue.push(e.target);
    }
  }
  for (const id of ids) {
    if (!ordered.includes(id)) ordered.push(id);
  }
  return ordered;
}

/** Push each edge's source port into the target node (topo order, one hop per edge). */
export function syncWiredData(nodes: Node<WfData>[], edges: Edge[]): Node<WfData>[] {
  if (!nodes.length || !edges.length) return nodes;
  const next = new Map(nodes.map((n) => [n.id, n]));
  let changed = false;
  for (const id of topoIds(nodes, edges)) {
    const node = next.get(id);
    if (!node) continue;
    const incoming = edges.filter((e) => e.target === id);
    if (!incoming.length) continue;
    let patch: Partial<WfData> = {};
    for (const e of incoming) {
      const src = next.get(e.source);
      if (!src) continue;
      patch = {
        ...patch,
        ...writeTargetPort(node.data.nodeType, e.targetHandle, readSourcePort(src.data, e.sourceHandle)),
      };
    }
    const data = applyDefined(node.data, patch);
    if (data !== node.data) {
      next.set(id, { ...node, data });
      changed = true;
    }
  }
  return changed ? nodes.map((n) => next.get(n.id) || n) : nodes;
}

/** Fill missing handles with the first compatible port pair. */
export function inferConnectionHandles(
  c: Connection,
  nodes: Node<WfData>[],
  edges: Edge[],
  contracts?: NodeContracts | null,
): Connection {
  if (c.sourceHandle && c.targetHandle) return c;
  const src = nodes.find((n) => n.id === c.source);
  const tgt = nodes.find((n) => n.id === c.target);
  if (!src || !tgt) return c;
  const outs = portsFor(src.data.nodeType, src.data).outputs;
  const ins = portsFor(tgt.data.nodeType, tgt.data).inputs;
  for (const o of outs) {
    for (const i of ins) {
      const next = { ...c, sourceHandle: o.id, targetHandle: i.id };
      if (isValidPortConnection(next, nodes, edges, contracts)) return next;
    }
  }
  return c;
}
