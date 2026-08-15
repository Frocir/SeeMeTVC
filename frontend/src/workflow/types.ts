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
  | "VideoReversePrompt"
  | "ImageCompare"
  | "SpeechToText"
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

export type MediaKind = "text" | "prompt" | "image" | "video" | "audio";

export type LlmRole = "chat" | "brief" | "shot";

export type Scene = {
  id?: string;
  index?: number;
  title?: string;
  start_time?: number | null;
  end_time?: number | null;
  frame_url?: string;
  score?: number;
  analysis?: string;
  prompt?: string;
  seedance_prompt?: string;
  midjourney_prompt?: string;
  jimeng_prompt?: string;
  narration?: string;
  negative_prompt?: string;
};

export type TimelineItem = {
  index: number;
  start_time: number;
  end_time: number;
  frame_url: string;
  score?: number;
};

export type TranscriptSegment = {
  start: number;
  end: number;
  text: string;
};

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
  frame_count?: number;
  frame_strategy?: "fixed" | "scene_detect";
  max_scenes?: number;
  scene_threshold?: number;
  sample_fps?: number;
  prompt_style?: "seedance" | "midjourney" | "jimeng" | "all";
  frames?: string[];
  timeline?: TimelineItem[];
  scenes?: Scene[];
  reference_video_url?: string;
  before_url?: string;
  after_url?: string;
  selected?: "before" | "after";
  compare_mode?: "slider" | "side_by_side";
  url?: string;
  media_url?: string;
  language?: string;
  segments?: TranscriptSegment[];
  srt?: string;
  size?: string;
  negative_prompt?: string;
  seed?: number;
  batch_size?: number;
  image_strength?: number;
  first_image_url?: string;
  last_image_url?: string;
  style_image_url?: string;
  character_image_url?: string;
  product_image_url?: string;
  reference_strength?: number;
  source_asset_version_id?: number;
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
  "ImageCompare",
  "SpeechToText",
  "ImageToVideo",
  "VideoTrim",
  "VideoMux",
  "MixAudio",
  "VideoDemux",
  "VideoReversePrompt",
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
