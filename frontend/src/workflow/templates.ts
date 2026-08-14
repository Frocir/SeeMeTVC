import type { Edge, Node } from "@xyflow/react";
import type { PaletteItem, WfData, WfNodeType } from "./types";

export const DEMO_BGM_URL = "/uploads/_mock/demo_bgm_v1.wav";
export const DEFAULT_SHOT_SECONDS = 5;

export const TTS_VOICES = [
  { id: "zh-CN-XiaoxiaoNeural", label: "晓晓（默认女声）" },
  { id: "zh-CN-XiaoyiNeural", label: "晓伊" },
  { id: "zh-CN-YunxiNeural", label: "云希（男）" },
  { id: "zh-CN-YunjianNeural", label: "云健（男）" },
  { id: "zh-CN-XiaochenNeural", label: "晓辰" },
];

export const LLM_SYSTEM = {
  chat: "",
  brief:
    "你是美妆 TVC 文案。根据用户给出的品牌、卖点、口号，写一段可直接给下游使用的 Brief。只输出正文，不要标题或 Markdown。",
  shot: '你是美妆广告单镜写手。根据 Brief 只写一镜。输出严格 JSON（不要 Markdown 围栏）：{"prompt":"该镜的画面提示词","narration":"一句适合口播的中文旁白，约 15–40 字"}。禁止 scenes 数组，禁止多镜。',
  shotSilent:
    '你是美妆广告单镜写手。根据 Brief 只写一镜。输出严格 JSON（不要 Markdown 围栏）：{"prompt":"该镜的画面提示词"}。不要 narration，禁止 scenes 数组，禁止多镜。',
};

export function shotSystem(wantNarration: boolean): string {
  return wantNarration ? LLM_SYSTEM.shot : LLM_SYSTEM.shotSilent;
}

export const PALETTE: PaletteItem[] = [
  { type: "TextAsset", label: "文本", hint: "Brief / 提示词" },
  { type: "ImageAsset", label: "图片", hint: "上传参考图" },
  { type: "VideoAsset", label: "视频", hint: "上传片段" },
  { type: "AudioAsset", label: "音频", hint: "BGM / 旁白文件" },
  { type: "LlmText", label: "LLM", hint: "检查器选用途：对话 / Brief / 单镜" },
  { type: "TextToImage", label: "文生图", hint: "文本/参考图 → 首帧图" },
  { type: "ImageToVideo", label: "图生视频", hint: "一镜一段；无图则文生" },
  { type: "TtsSpeak", label: "TTS 口播", hint: "aisrv Edge TTS" },
  { type: "VideoTrim", label: "裁时长", hint: "裁画面秒数" },
  { type: "AudioTrim", label: "音频裁切", hint: "裁 BGM / 口播起止秒" },
  { type: "VideoMux", label: "真拼接", hint: "只拼画面；多镜手搭" },
  { type: "VideoDemux", label: "拆音轨", hint: "有声 → 静音+音频；无音轨失败" },
  { type: "VideoReversePrompt", label: "视频反推", hint: "参考视频 → 分镜 prompt" },
  { type: "MixAudio", label: "混音", hint: "画面+BGM+口播，三口必接" },
  { type: "SubtitleBurn", label: "字幕", hint: "把 slogan 烧进成片" },
];

export function defaultData(type: WfNodeType, modelId = ""): WfData {
  const label = PALETTE.find((p) => p.type === type)?.label || type;
  switch (type) {
    case "TextAsset":
    case "BriefInput":
    case "ScenePlan":
      return {
        nodeType: "TextAsset",
        label: type === "BriefInput" ? "文案" : type === "ScenePlan" ? "文本" : label,
        textRole: "brief",
        brand: "SeeMe",
        selling_points: "水光肌、持妆、气色",
        slogan: "看见更好的自己",
        prompt: "高端美妆广告短片，柔光特写",
        text: "",
      };
    case "ImageAsset":
    case "MakeupControl":
      return { nodeType: "ImageAsset", label: type === "MakeupControl" ? "图片" : label };
    case "VideoAsset":
    case "PreviewOut":
      return { nodeType: "VideoAsset", label };
    case "ImageToVideo":
    case "ShotGenerate":
      return {
        nodeType: "ImageToVideo",
        label: type === "ShotGenerate" ? "图生视频" : label,
        model_id: modelId,
        duration_seconds: DEFAULT_SHOT_SECONDS,
      };
    case "TextToImage":
      return { nodeType: "TextToImage", label, model_id: "t2i-local-simulate" };
    case "VideoTrim":
      return {
        nodeType: "VideoTrim",
        label,
        trim_start: 0,
        trim_end: DEFAULT_SHOT_SECONDS,
      };
    case "VideoMux":
    case "TimelineMux":
      return { nodeType: "VideoMux", label: type === "TimelineMux" ? "拼接" : label, aspect: "16:9" };
    case "AudioAsset":
      return { nodeType: "AudioAsset", label, audio_url: "" };
    case "MixAudio":
      return { nodeType: "MixAudio", label };
    case "VideoDemux":
      return { nodeType: "VideoDemux", label };
    case "VideoReversePrompt":
      return {
        nodeType: "VideoReversePrompt",
        label,
        frame_count: 3,
        frame_strategy: "scene_detect",
        max_scenes: 6,
        scene_threshold: 0.28,
        sample_fps: 2,
        prompt_style: "seedance",
        prompt: "",
      };
    case "AudioTrim":
      return { nodeType: "AudioTrim", label, trim_start: 0, trim_end: 0 };
    case "SubtitleBurn":
      return { nodeType: "SubtitleBurn", label, text: "" };
    case "TtsSpeak":
      return {
        nodeType: "TtsSpeak",
        label,
        model_id: "tts-1",
        voice: "zh-CN-XiaoxiaoNeural",
        text: "",
      };
    case "LlmText":
    case "LlmChat":
    case "LlmBrief":
    case "LlmStoryboard":
    case "LlmShot": {
      const role =
        type === "LlmBrief" ? "brief" : type === "LlmChat" ? "chat" : "shot";
      return {
        nodeType: "LlmText",
        label: "LLM",
        llmRole: role,
        system_prompt: role === "shot" ? shotSystem(true) : LLM_SYSTEM[role],
        model_id: "llm-local-simulate",
        wantNarration: role === "shot",
        prompt: "",
        text: "",
      };
    }
    default:
      return { nodeType: "TextAsset", label };
  }
}

function edge(
  id: string,
  source: string,
  target: string,
  sourceHandle: string,
  targetHandle: string,
): Edge {
  return { id, source, target, sourceHandle, targetHandle };
}

export type WfTemplateId = "beauty_linear" | "quick_shot";

export type WfTemplate = {
  id: WfTemplateId;
  name: string;
  hint: string;
  build: (modelId: string) => { nodes: Node<WfData>[]; edges: Edge[] };
};

export function defaultGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  return beautyLinearGraph(modelId);
}

const NODE_W = 300;
const NODE_H = 320;
const GAP_X = 140;
const GAP_Y = 120;
const COL = NODE_W + GAP_X;
const ROW = NODE_H + GAP_Y;
const ORIGIN_X = 64;
const ORIGIN_Y = 64;

function at(col: number, row: number) {
  return { x: ORIGIN_X + col * COL, y: ORIGIN_Y + row * ROW };
}

function beautyLinearGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  const nodes: Node<WfData>[] = [
    {
      id: "brief",
      type: "media",
      position: at(0, 0),
      data: { ...defaultData("TextAsset", modelId), label: "品牌 Brief", textRole: "brief" },
    },
    {
      id: "llm",
      type: "media",
      position: at(1, 0),
      data: {
        ...defaultData("LlmText", modelId),
        label: "LLM 单镜",
        llmRole: "shot",
        wantNarration: true,
        system_prompt: shotSystem(true),
      },
    },
    {
      id: "t2i",
      type: "media",
      position: at(2, 0),
      data: { ...defaultData("TextToImage", modelId), label: "文生图" },
    },
    {
      id: "i2v",
      type: "media",
      position: at(3, 0),
      data: {
        ...defaultData("ImageToVideo", modelId),
        label: "图生视频",
        duration_seconds: DEFAULT_SHOT_SECONDS,
      },
    },
    {
      id: "trim",
      type: "media",
      position: at(4, 0),
      data: {
        ...defaultData("VideoTrim", modelId),
        label: "裁时长",
        trim_start: 0,
        trim_end: DEFAULT_SHOT_SECONDS,
      },
    },
    {
      id: "tts",
      type: "media",
      position: at(2, 1),
      data: { ...defaultData("TtsSpeak", modelId), label: "TTS 口播" },
    },
    {
      id: "atrim",
      type: "media",
      position: at(3, 1),
      data: { ...defaultData("AudioTrim", modelId), label: "音频裁切" },
    },
    {
      id: "bgm",
      type: "media",
      position: at(4, 1),
      data: {
        ...defaultData("AudioAsset", modelId),
        label: "BGM（演示床垫）",
        audio_url: DEMO_BGM_URL,
      },
    },
    {
      id: "mix",
      type: "media",
      position: at(5, 0),
      data: { ...defaultData("MixAudio", modelId), label: "混音" },
    },
    {
      id: "sub",
      type: "media",
      position: at(6, 0),
      data: { ...defaultData("SubtitleBurn", modelId), label: "字幕" },
    },
  ];
  const edges: Edge[] = [
    edge("e1", "brief", "llm", "text", "text"),
    edge("e2", "llm", "t2i", "text", "prompt"),
    edge("e3", "t2i", "i2v", "image", "image"),
    edge("e4", "llm", "i2v", "text", "prompt"),
    edge("e5", "i2v", "trim", "video", "video"),
    edge("e6", "llm", "tts", "narration", "text"),
    edge("e7", "tts", "atrim", "audio", "audio"),
    edge("e8", "atrim", "mix", "audio", "vo"),
    edge("e9", "bgm", "mix", "audio", "bgm"),
    edge("e10", "trim", "mix", "video", "video"),
    edge("e11", "mix", "sub", "video", "video"),
    edge("e12", "brief", "sub", "text", "text"),
  ];
  return { nodes, edges };
}

function quickShotGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  const nodes: Node<WfData>[] = [
    {
      id: "brief",
      type: "media",
      position: at(0, 0),
      data: { ...defaultData("TextAsset", modelId), label: "Brief" },
    },
    {
      id: "llm",
      type: "media",
      position: at(1, 0),
      data: {
        ...defaultData("LlmText", modelId),
        label: "LLM 单镜",
        llmRole: "shot",
        wantNarration: false,
        system_prompt: shotSystem(false),
      },
    },
    {
      id: "t2i",
      type: "media",
      position: at(2, 0),
      data: { ...defaultData("TextToImage", modelId) },
    },
    {
      id: "i2v",
      type: "media",
      position: at(3, 0),
      data: { ...defaultData("ImageToVideo", modelId) },
    },
  ];
  const edges: Edge[] = [
    edge("e1", "brief", "llm", "text", "text"),
    edge("e2", "llm", "t2i", "text", "prompt"),
    edge("e3", "t2i", "i2v", "image", "image"),
    edge("e4", "llm", "i2v", "text", "prompt"),
  ];
  return { nodes, edges };
}

export const WF_TEMPLATES: WfTemplate[] = [
  {
    id: "beauty_linear",
    name: "有声一条龙",
    hint: "Brief → LLM → 文生图 → 图生 → 裁切 → TTS → 音频裁切 → 混音 → 字幕",
    build: beautyLinearGraph,
  },
  {
    id: "quick_shot",
    name: "无声快出",
    hint: "Brief → LLM → 文生图 → 图生视频",
    build: quickShotGraph,
  },
];
