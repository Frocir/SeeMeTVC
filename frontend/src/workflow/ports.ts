import type { Connection, Edge } from "@xyflow/react";
import { normalizeNodeType, type PortDef, type WfNodeType } from "./types";

export const NODE_PORTS: Record<string, { inputs: PortDef[]; outputs: PortDef[] }> = {
  TextAsset: {
    inputs: [],
    outputs: [{ id: "text", label: "text", kind: "text" }],
  },
  ImageAsset: {
    inputs: [],
    outputs: [{ id: "image", label: "image", kind: "image" }],
  },
  VideoAsset: {
    inputs: [{ id: "video", label: "video", kind: "video" }],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
  AudioAsset: {
    inputs: [],
    outputs: [{ id: "audio", label: "audio", kind: "audio" }],
  },
  LlmText: {
    inputs: [{ id: "text", label: "text", kind: "text" }],
    outputs: [
      { id: "text", label: "text", kind: "text" },
      { id: "narration", label: "旁白", kind: "text" },
    ],
  },
  TextToImage: {
    inputs: [
      { id: "prompt", label: "prompt", kind: "text" },
      { id: "image", label: "参考图", kind: "image" },
    ],
    outputs: [{ id: "image", label: "image", kind: "image" }],
  },
  ImageToVideo: {
    inputs: [
      { id: "prompt", label: "prompt", kind: "text" },
      { id: "image", label: "image", kind: "image" },
    ],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
  VideoTrim: {
    inputs: [{ id: "video", label: "video", kind: "video" }],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
  VideoMux: {
    inputs: [{ id: "video", label: "video", kind: "video" }],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
  MixAudio: {
    inputs: [
      { id: "video", label: "video", kind: "video" },
      { id: "bgm", label: "BGM", kind: "audio" },
      { id: "vo", label: "口播", kind: "audio" },
    ],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
  VideoDemux: {
    inputs: [{ id: "video", label: "video", kind: "video" }],
    outputs: [
      { id: "video", label: "video", kind: "video" },
      { id: "audio", label: "audio", kind: "audio" },
    ],
  },
  VideoReversePrompt: {
    inputs: [{ id: "video", label: "video", kind: "video" }],
    outputs: [
      { id: "text", label: "分析", kind: "text" },
      { id: "prompt", label: "prompt", kind: "prompt" },
      { id: "scenes", label: "分镜", kind: "text" },
      { id: "frames", label: "关键帧", kind: "image" },
      { id: "timeline", label: "时间轴", kind: "text" },
    ],
  },
  AudioTrim: {
    inputs: [{ id: "audio", label: "audio", kind: "audio" }],
    outputs: [{ id: "audio", label: "audio", kind: "audio" }],
  },
  TtsSpeak: {
    inputs: [{ id: "text", label: "text", kind: "text" }],
    outputs: [{ id: "audio", label: "audio", kind: "audio" }],
  },
  SubtitleBurn: {
    inputs: [
      { id: "video", label: "video", kind: "video" },
      { id: "text", label: "text", kind: "text" },
    ],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
};

const KIND_COMPAT: Record<string, string[]> = {
  text: ["text", "prompt"],
  image: ["image"],
  video: ["video"],
  audio: ["audio", "bgm", "vo"],
  narration: ["text", "prompt"],
  prompt: ["prompt", "text"],
  bgm: ["bgm", "audio"],
  vo: ["vo", "audio"],
};

export function portsFor(nodeType: WfNodeType, data?: { wantNarration?: boolean; llmRole?: string }) {
  const key = normalizeNodeType(nodeType);
  const ports = NODE_PORTS[key] || NODE_PORTS.TextAsset;
  if (key === "LlmText" && data && data.wantNarration === false) {
    return { ...ports, outputs: ports.outputs.filter((p) => p.id !== "narration") };
  }
  return ports;
}

export function dropClosedNarrationEdges<T extends { source: string; sourceHandle?: string | null }>(
  nodes: { id: string; data?: { wantNarration?: boolean } }[],
  edges: T[],
): T[] {
  const closed = new Set(nodes.filter((n) => n.data?.wantNarration === false).map((n) => n.id));
  if (!closed.size) return edges;
  return edges.filter((e) => !(closed.has(e.source) && e.sourceHandle === "narration"));
}

export type PortNodeRef = { id: string; data: { nodeType: WfNodeType; wantNarration?: boolean; llmRole?: string } };
export type PortEdgeRef = { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null };

type PortContracts = {
  kind_compat?: Record<string, string[]>;
  forbid_edges?: Array<{ source_type?: string; target_type?: string; target_handle?: string; source_fed_by?: string }>;
} | null;

function portKind(node: PortNodeRef | undefined, which: "inputs" | "outputs", handle: string | undefined): string {
  if (!node || !handle) return handle || "";
  const ports = portsFor(node.data.nodeType, node.data)[which];
  return ports.find((p) => p.id === handle)?.kind || handle;
}

function isTtsLike(
  sourceId: string,
  nodes: PortNodeRef[] | undefined,
  edges: PortEdgeRef[] | undefined,
): boolean {
  const src = nodes?.find((n) => n.id === sourceId);
  if (!src) return false;
  const nt = normalizeNodeType(src.data.nodeType);
  if (nt === "TtsSpeak") return true;
  if (nt === "AudioTrim" && edges) {
    return edges.some((e) => e.target === sourceId && isTtsLike(e.source, nodes, edges));
  }
  return false;
}

export function isValidPortConnection(
  c: Connection | Edge,
  nodes?: PortNodeRef[],
  edges?: PortEdgeRef[],
  contracts?: PortContracts,
): boolean {
  const sh = c.sourceHandle ?? undefined;
  const th = c.targetHandle ?? undefined;
  if (th === "bgm" && c.source && isTtsLike(String(c.source), nodes, edges)) {
    return false;
  }
  if (contracts?.forbid_edges && c.source && c.target && nodes) {
    const src = nodes.find((n) => n.id === String(c.source));
    const tgt = nodes.find((n) => n.id === String(c.target));
    if (src && tgt) {
      const st = normalizeNodeType(src.data.nodeType);
      const tt = normalizeNodeType(tgt.data.nodeType);
      for (const rule of contracts.forbid_edges) {
        if (rule.target_type !== tt) continue;
        if (rule.target_handle && rule.target_handle !== (th || "")) continue;
        if (rule.source_type !== st) continue;
        if (rule.source_fed_by && !isTtsLike(String(c.source), nodes, edges)) continue;
        return false;
      }
    }
  }
  if (!sh || !th) return true;
  const src = nodes?.find((n) => n.id === String(c.source));
  const tgt = nodes?.find((n) => n.id === String(c.target));
  const sourceKind = portKind(src, "outputs", sh) || sh;
  const targetKind = portKind(tgt, "inputs", th) || th;
  if (sourceKind === targetKind) return true;
  if (sourceKind === "clips" && targetKind === "video") return true;
  if (sourceKind === "video" && targetKind === "clips") return true;
  const compat = contracts?.kind_compat || KIND_COMPAT;
  return (compat[sourceKind] || []).includes(targetKind);
}
