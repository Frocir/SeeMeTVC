/** Canvas node types. Legacy names still normalize on load; old graphs are not guaranteed to run. */
export type WfNodeType =
  | "TextAsset"
  | "ImageAsset"
  | "VideoAsset"
  | "AudioAsset"
  | "LlmText"
  | "TextToImage"
  | "ImageToVideo"
  | "VideoTrim"
  | "VideoMux"
  | "MixAudio"
  | "VideoDemux"
  | "AudioTrim"
  | "TtsSpeak"
  | "SubtitleBurn"
  // Legacy aliases (loaded graphs)
  | "LlmChat"
  | "LlmBrief"
  | "LlmStoryboard"
  | "LlmShot"
  | "BriefInput"
  | "ScenePlan"
  | "MakeupControl"
  | "ShotGenerate"
  | "TimelineMux"
  | "PreviewOut";

export type MediaKind = "text" | "image" | "video" | "audio";

export type LlmRole = "chat" | "brief" | "shot";

export type WfData = {
  nodeType: WfNodeType;
  label: string;
  textRole?: "brief" | "prompt" | "notes";
  llmRole?: LlmRole;
  /** Shot role only. Default true. False = no 旁白 port / field. */
  wantNarration?: boolean;
  brand?: string;
  selling_points?: string;
  slogan?: string;
  prompt?: string;
  text?: string;
  system_prompt?: string;
  narration?: string;
  image_url?: string;
  audio_url?: string;
  style_hint?: string;
  model_id?: string;
  voice?: string;
  duration_seconds?: number;
  aspect?: string;
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
  kind: MediaKind;
};

export type PaletteItem = {
  type: WfNodeType;
  label: string;
  hint: string;
};

export const EXIT_NODE_TYPES: WfNodeType[] = [
  "TextToImage",
  "ImageToVideo",
  "VideoTrim",
  "VideoMux",
  "MixAudio",
  "VideoDemux",
  "AudioTrim",
  "SubtitleBurn",
  "ShotGenerate",
  "TimelineMux",
];

export const LLM_NODE_TYPES: WfNodeType[] = [
  "LlmText",
  "LlmChat",
  "LlmBrief",
  "LlmStoryboard",
  "LlmShot",
];

export const GENERATABLE_NODE_TYPES: WfNodeType[] = [
  ...EXIT_NODE_TYPES,
  ...LLM_NODE_TYPES,
  "TtsSpeak",
  "TextAsset",
];

export const LEGACY_TO_FREE: Record<string, WfNodeType> = {
  BriefInput: "TextAsset",
  ScenePlan: "TextAsset",
  MakeupControl: "ImageAsset",
  ShotGenerate: "ImageToVideo",
  TimelineMux: "VideoMux",
  PreviewOut: "VideoAsset",
  LlmChat: "LlmText",
  LlmBrief: "LlmText",
  LlmStoryboard: "LlmText",
  LlmShot: "LlmText",
};

const LLM_ROLE_FROM_LEGACY: Record<string, LlmRole> = {
  LlmChat: "chat",
  LlmBrief: "brief",
  LlmStoryboard: "shot",
  LlmShot: "shot",
};

export function legacyLlmRole(declared: string): LlmRole | undefined {
  return LLM_ROLE_FROM_LEGACY[declared];
}

export function normalizeNodeType(raw: string | undefined | null): WfNodeType {
  const t = (raw || "TextAsset") as WfNodeType;
  return (LEGACY_TO_FREE[t] as WfNodeType) || t;
}

export function isExitNodeType(t: WfNodeType): boolean {
  return EXIT_NODE_TYPES.includes(t) || EXIT_NODE_TYPES.includes(normalizeNodeType(t));
}

export function isLlmNodeType(t: WfNodeType): boolean {
  const n = normalizeNodeType(t);
  return n === "LlmText" || LLM_NODE_TYPES.includes(n) || LLM_NODE_TYPES.includes(t);
}

export function isGeneratableNodeType(t: WfNodeType): boolean {
  const n = normalizeNodeType(t);
  return GENERATABLE_NODE_TYPES.includes(n) || GENERATABLE_NODE_TYPES.includes(t);
}
