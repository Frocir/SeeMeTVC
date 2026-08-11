import type { Connection, Edge } from "@xyflow/react";
import { normalizeNodeType, type PortDef, type WfNodeType } from "./types";

/** Slot-aware ports for freeform nodes (+ legacy mapped shapes). */
export const NODE_PORTS: Record<string, { inputs: PortDef[]; outputs: PortDef[] }> = {
  TextAsset: {
    inputs: [],
    outputs: [{ id: "text", label: "text", kind: "text" }],
  },
  ImageAsset: {
    inputs: [{ id: "text", label: "text", kind: "text" }],
    outputs: [{ id: "image", label: "image", kind: "image" }],
  },
  VideoAsset: {
    inputs: [{ id: "video", label: "video", kind: "video" }],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
  ImageToVideo: {
    inputs: [
      { id: "prompt", label: "prompt", kind: "text" },
      { id: "image", label: "image", kind: "image" },
    ],
    outputs: [
      { id: "video", label: "video", kind: "video" },
      { id: "clips", label: "clips", kind: "clips" },
    ],
  },
  VideoTrim: {
    inputs: [{ id: "video", label: "video", kind: "video" }],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
  VideoMux: {
    inputs: [{ id: "clips", label: "clips", kind: "clips" }],
    outputs: [{ id: "video", label: "video", kind: "video" }],
  },
  // Legacy port ids kept for old drafts until convert
  BriefInput: {
    inputs: [],
    outputs: [{ id: "brief", label: "brief", kind: "text" }],
  },
  ScenePlan: {
    inputs: [{ id: "brief", label: "brief", kind: "text" }],
    outputs: [{ id: "scenes", label: "scenes", kind: "text" }],
  },
  MakeupControl: {
    inputs: [{ id: "brief", label: "brief", kind: "text" }],
    outputs: [{ id: "makeup", label: "makeup", kind: "image" }],
  },
  ShotGenerate: {
    inputs: [
      { id: "scenes", label: "scenes", kind: "text" },
      { id: "makeup", label: "makeup", kind: "image" },
      { id: "brief", label: "brief", kind: "text" },
    ],
    outputs: [{ id: "clips", label: "clips", kind: "clips" }],
  },
  TimelineMux: {
    inputs: [{ id: "clips", label: "clips", kind: "clips" }],
    outputs: [{ id: "timeline", label: "timeline", kind: "video" }],
  },
  PreviewOut: {
    inputs: [
      { id: "timeline", label: "timeline", kind: "video" },
      { id: "clips", label: "clips", kind: "clips" },
    ],
    outputs: [{ id: "result", label: "result", kind: "video" }],
  },
};

/** Source handle kind → acceptable target handle kinds */
const KIND_COMPAT: Record<string, string[]> = {
  text: ["text", "prompt", "brief", "scenes"],
  image: ["image", "makeup"],
  video: ["video", "timeline", "result", "clips"],
  clips: ["clips", "video", "timeline"],
  // legacy ids treated as their kinds
  brief: ["text", "prompt", "brief", "scenes"],
  scenes: ["text", "prompt", "scenes", "brief"],
  makeup: ["image", "makeup"],
  timeline: ["video", "timeline", "result", "clips"],
  result: ["video", "result", "timeline"],
  prompt: ["prompt", "text", "brief"],
};

export function portsFor(nodeType: WfNodeType) {
  const key = normalizeNodeType(nodeType);
  return NODE_PORTS[nodeType] || NODE_PORTS[key] || NODE_PORTS.TextAsset;
}

export function isValidPortConnection(c: Connection | Edge): boolean {
  const sh = c.sourceHandle ?? undefined;
  const th = c.targetHandle ?? undefined;
  if (!sh || !th) return true;
  if (sh === th) return true;
  return (KIND_COMPAT[sh] || []).includes(th);
}
