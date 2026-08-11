/** Freeform LibTV-style canvas kinds (V1). Legacy 6 types still accepted via normalize. */
export type WfNodeType =
  | "TextAsset"
  | "ImageAsset"
  | "VideoAsset"
  | "ImageToVideo"
  | "VideoTrim"
  | "VideoMux"
  // Legacy aliases (loaded graphs / old drafts)
  | "BriefInput"
  | "ScenePlan"
  | "MakeupControl"
  | "ShotGenerate"
  | "TimelineMux"
  | "PreviewOut";

export type MediaKind = "text" | "image" | "video" | "clips";

export type WfData = {
  nodeType: WfNodeType;
  label: string;
  /** Optional role for TextAsset in beauty templates */
  textRole?: "brief" | "script" | "prompt" | "notes";
  brand?: string;
  selling_points?: string;
  slogan?: string;
  prompt?: string;
  text?: string;
  image_url?: string;
  scene_count?: number;
  style_hint?: string;
  model_id?: string;
  duration_seconds?: number;
  use_scenes?: boolean;
  max_shots?: number;
  intensity?: number;
  before_prompt?: string;
  after_prompt?: string;
  aspect?: string;
  pick?: string;
  /** Trim window in seconds */
  trim_start?: number;
  trim_end?: number;
  preview_url?: string;
  clip_url?: string;
  result_url?: string;
  runStatus?: string;
  runError?: string;
  runOutput?: Record<string, unknown> | null;
  stale?: boolean;
  simulated?: boolean;
};

export type PortDef = {
  id: string;
  label: string;
  /** Data kind for slot matching */
  kind: MediaKind;
};

export type PaletteItem = {
  type: WfNodeType;
  label: string;
  hint: string;
};

export const EXIT_NODE_TYPES: WfNodeType[] = ["ImageToVideo", "VideoTrim", "VideoMux", "ShotGenerate", "TimelineMux"];

export const LEGACY_TO_FREE: Record<string, WfNodeType> = {
  BriefInput: "TextAsset",
  ScenePlan: "TextAsset",
  MakeupControl: "ImageAsset",
  ShotGenerate: "ImageToVideo",
  TimelineMux: "VideoMux",
  PreviewOut: "VideoAsset",
};

export function normalizeNodeType(raw: string | undefined | null): WfNodeType {
  const t = (raw || "TextAsset") as WfNodeType;
  return (LEGACY_TO_FREE[t] as WfNodeType) || t;
}

export function isExitNodeType(t: WfNodeType): boolean {
  return EXIT_NODE_TYPES.includes(t) || EXIT_NODE_TYPES.includes(normalizeNodeType(t));
}
