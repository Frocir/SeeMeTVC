import type { Edge, Node } from "@xyflow/react";
import { NODE_TYPE_HINT, NODE_TYPE_LABEL } from "./labels";
import type { PaletteItem, WfData, WfNodeType } from "./types";

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
  briefHardware:
    "你是硬件与科创产品广告文案。根据品牌、卖点、口号，写一段可直接给下游使用的 Brief：突出结构、材质、装配和能落地的工程感。只输出正文，不要标题或 Markdown。",
  shot: '你是美妆广告单镜写手。根据 Brief 只写一镜。输出严格 JSON（不要 Markdown 围栏）：{"prompt":"该镜的画面提示词","narration":"一句适合口播的中文旁白，约 15–40 字"}。禁止 scenes 数组，禁止多镜。',
  shotSilent:
    '你是美妆广告单镜写手。根据 Brief 只写一镜。输出严格 JSON（不要 Markdown 围栏）：{"prompt":"该镜的画面提示词"}。不要 narration，禁止 scenes 数组，禁止多镜。',
  shotHardware:
    '你是硬件/科创产品单镜写手。根据 Brief 只写一镜：工业顶光、金属或工程塑料、装配或工位、产品结构清晰。输出严格 JSON（不要 Markdown 围栏）：{"prompt":"该镜的画面提示词，英文画面词","narration":"一句适合口播的中文旁白，约 15–40 字"}。禁止 scenes 数组，禁止多镜。',
  shotHardwareSilent:
    '你是硬件/科创产品单镜写手。根据 Brief 只写一镜：工业顶光、金属或工程塑料、装配或工位、产品结构清晰。输出严格 JSON（不要 Markdown 围栏）：{"prompt":"该镜的画面提示词，英文画面词"}。不要 narration，禁止 scenes 数组，禁止多镜。',
};

export function shotSystem(wantNarration: boolean): string {
  return wantNarration ? LLM_SYSTEM.shot : LLM_SYSTEM.shotSilent;
}

export function hardwareShotSystem(wantNarration: boolean): string {
  return wantNarration ? LLM_SYSTEM.shotHardware : LLM_SYSTEM.shotHardwareSilent;
}

export const PALETTE_GROUPS: { title: string; items: PaletteItem[] }[] = [
  {
    title: "素材",
    items: [
      { type: "TextAsset", label: NODE_TYPE_LABEL.TextAsset, hint: NODE_TYPE_HINT.TextAsset },
      { type: "ImageAsset", label: NODE_TYPE_LABEL.ImageAsset, hint: NODE_TYPE_HINT.ImageAsset },
      { type: "VideoAsset", label: NODE_TYPE_LABEL.VideoAsset, hint: NODE_TYPE_HINT.VideoAsset },
      { type: "AudioAsset", label: NODE_TYPE_LABEL.AudioAsset, hint: NODE_TYPE_HINT.AudioAsset },
    ],
  },
  {
    title: "生成",
    items: [
      { type: "LlmText", label: NODE_TYPE_LABEL.LlmText, hint: NODE_TYPE_HINT.LlmText },
      { type: "TextToImage", label: NODE_TYPE_LABEL.TextToImage, hint: NODE_TYPE_HINT.TextToImage },
      { type: "ImageToVideo", label: NODE_TYPE_LABEL.ImageToVideo, hint: NODE_TYPE_HINT.ImageToVideo },
      { type: "VideoReversePrompt", label: NODE_TYPE_LABEL.VideoReversePrompt, hint: NODE_TYPE_HINT.VideoReversePrompt },
      { type: "ImageCompare", label: NODE_TYPE_LABEL.ImageCompare, hint: NODE_TYPE_HINT.ImageCompare },
      { type: "SpeechToText", label: NODE_TYPE_LABEL.SpeechToText, hint: NODE_TYPE_HINT.SpeechToText },
      { type: "TtsSpeak", label: NODE_TYPE_LABEL.TtsSpeak, hint: NODE_TYPE_HINT.TtsSpeak },
    ],
  },
  {
    title: "剪辑",
    items: [
      { type: "VideoTrim", label: NODE_TYPE_LABEL.VideoTrim, hint: NODE_TYPE_HINT.VideoTrim },
      { type: "AudioTrim", label: NODE_TYPE_LABEL.AudioTrim, hint: NODE_TYPE_HINT.AudioTrim },
      { type: "VideoMux", label: NODE_TYPE_LABEL.VideoMux, hint: NODE_TYPE_HINT.VideoMux },
      { type: "VideoDemux", label: NODE_TYPE_LABEL.VideoDemux, hint: NODE_TYPE_HINT.VideoDemux },
      { type: "MixAudio", label: NODE_TYPE_LABEL.MixAudio, hint: NODE_TYPE_HINT.MixAudio },
      { type: "SubtitleBurn", label: NODE_TYPE_LABEL.SubtitleBurn, hint: NODE_TYPE_HINT.SubtitleBurn },
    ],
  },
];

export const PALETTE: PaletteItem[] = PALETTE_GROUPS.flatMap((g) => g.items);

export function defaultData(type: WfNodeType, modelId = ""): WfData {
  const label = PALETTE.find((p) => p.type === type)?.label || type;
  switch (type) {
    case "TextAsset":
    case "BriefInput":
    case "ScenePlan":
      return {
        nodeType: "TextAsset",
        label: type === "BriefInput" ? "文案" : type === "ScenePlan" ? "文案" : label,
        textRole: "brief",
        brand: "GlamPilot",
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
        label: type === "ShotGenerate" ? NODE_TYPE_LABEL.ImageToVideo : label,
        model_id: modelId || "seedance-2.5",
        duration_seconds: DEFAULT_SHOT_SECONDS,
      };
    case "TextToImage":
      return { nodeType: "TextToImage", label, model_id: modelId };
    case "ImageCompare":
      return {
        nodeType: "ImageCompare",
        label,
        compare_mode: "slider",
        selected: "after",
      };
    case "SpeechToText":
      return {
        nodeType: "SpeechToText",
        label,
        language: "zh",
        model_id: modelId,
        text: "",
        srt: "",
      };
    case "VideoTrim":
      return {
        nodeType: "VideoTrim",
        label,
        trim_start: 0,
        trim_end: DEFAULT_SHOT_SECONDS,
      };
    case "VideoMux":
    case "TimelineMux":
      return { nodeType: "VideoMux", label: type === "TimelineMux" ? NODE_TYPE_LABEL.VideoMux : label, aspect: "16:9" };
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
        label: "写镜头",
        llmRole: role,
        system_prompt: role === "shot" ? shotSystem(true) : LLM_SYSTEM[role],
        model_id: modelId,
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

export type WfTemplateId =
  | "beauty_linear"
  | "quick_shot"
  | "hardware_linear"
  | "hardware_lab"
  | "hardware_quick";

export type WfTemplateKind = "beauty" | "hardware";

export type WfTemplate = {
  id: WfTemplateId;
  name: string;
  hint: string;
  kind: WfTemplateKind;
  build: (modelId: string) => { nodes: Node<WfData>[]; edges: Edge[] };
};

function hardwareBriefData(modelId: string): WfData {
  return {
    ...defaultData("TextAsset", modelId),
    label: "产品文案",
    textRole: "brief",
    brand: "科创工坊",
    selling_points: "开模快、能打样、供应链近",
    slogan: "在深圳，把想法做成机器",
    prompt:
      "Industrial hardware TVC, aluminum CNC body, workshop overhead light, macro of screws and heat vents, clean Shenzhen maker-lab commercial, 16:9",
    text: "",
  };
}

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
      data: { ...defaultData("TextAsset", modelId), label: "品牌文案", textRole: "brief" },
    },
    {
      id: "llm",
      type: "media",
      position: at(1, 0),
      data: {
        ...defaultData("LlmText", modelId),
        label: "写这一镜",
        llmRole: "shot",
        wantNarration: true,
        system_prompt: shotSystem(true),
      },
    },
    {
      id: "t2i",
      type: "media",
      position: at(2, 0),
      data: { ...defaultData("TextToImage", modelId), label: "出图" },
    },
    {
      id: "i2v",
      type: "media",
      position: at(3, 0),
      data: {
        ...defaultData("ImageToVideo", modelId),
        label: "出视频",
        duration_seconds: DEFAULT_SHOT_SECONDS,
      },
    },
    {
      id: "trim",
      type: "media",
      position: at(4, 0),
      data: {
        ...defaultData("VideoTrim", modelId),
        label: "裁视频",
        trim_start: 0,
        trim_end: DEFAULT_SHOT_SECONDS,
      },
    },
    {
      id: "tts",
      type: "media",
      position: at(2, 1),
      data: { ...defaultData("TtsSpeak", modelId), label: "配音" },
    },
    {
      id: "atrim",
      type: "media",
      position: at(3, 1),
      data: { ...defaultData("AudioTrim", modelId), label: "裁音频" },
    },
    {
      id: "bgm",
      type: "media",
      position: at(4, 1),
      data: {
        ...defaultData("AudioAsset", modelId),
        label: "配乐",
        audio_url: "",
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
      data: { ...defaultData("SubtitleBurn", modelId), label: "加字幕" },
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
      data: { ...defaultData("TextAsset", modelId), label: "品牌文案" },
    },
    {
      id: "llm",
      type: "media",
      position: at(1, 0),
      data: {
        ...defaultData("LlmText", modelId),
        label: "写这一镜",
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

function hardwareLinearGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  const g = beautyLinearGraph(modelId);
  return {
    nodes: g.nodes.map((n) => {
      if (n.id === "brief") {
        return { ...n, data: hardwareBriefData(modelId) };
      }
      if (n.id === "llm") {
        return {
          ...n,
          data: {
            ...n.data,
            system_prompt: hardwareShotSystem(true),
          },
        };
      }
      return n;
    }),
    edges: g.edges,
  };
}

function hardwareQuickGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  const g = quickShotGraph(modelId);
  return {
    nodes: g.nodes.map((n) => {
      if (n.id === "brief") {
        return { ...n, data: hardwareBriefData(modelId) };
      }
      if (n.id === "llm") {
        return {
          ...n,
          data: {
            ...n.data,
            system_prompt: hardwareShotSystem(false),
          },
        };
      }
      return n;
    }),
    edges: g.edges,
  };
}

function hardwareLabGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  const nodes: Node<WfData>[] = [
    {
      id: "brief",
      type: "media",
      position: at(0, 0),
      data: {
        ...hardwareBriefData(modelId),
        label: "学院 Brief",
        selling_points: "动手做、能打样、靠近供应链",
        slogan: "工位上的科创学院",
        prompt:
          "Shenzhen hardware academy workshop TVC, students assembling a prototype at a clean bench, PCB and CNC parts, cool overhead practicals, documentary-commercial hybrid, 16:9",
      },
    },
    {
      id: "product",
      type: "media",
      position: at(0, 1),
      data: {
        ...defaultData("ImageAsset", modelId),
        label: "样机 / 板卡",
      },
    },
    {
      id: "llm",
      type: "media",
      position: at(1, 0),
      data: {
        ...defaultData("LlmText", modelId),
        label: "写这一镜",
        llmRole: "shot",
        wantNarration: true,
        system_prompt: hardwareShotSystem(true),
      },
    },
    {
      id: "t2i",
      type: "media",
      position: at(2, 0),
      data: { ...defaultData("TextToImage", modelId), label: "工位氛围图" },
    },
    {
      id: "i2v",
      type: "media",
      position: at(3, 0),
      data: {
        ...defaultData("ImageToVideo", modelId),
        label: "出视频",
        duration_seconds: DEFAULT_SHOT_SECONDS,
      },
    },
    {
      id: "tts",
      type: "media",
      position: at(2, 1),
      data: { ...defaultData("TtsSpeak", modelId), label: "配音" },
    },
    {
      id: "mix",
      type: "media",
      position: at(4, 0),
      data: { ...defaultData("MixAudio", modelId), label: "混音" },
    },
    {
      id: "sub",
      type: "media",
      position: at(5, 0),
      data: { ...defaultData("SubtitleBurn", modelId), label: "加字幕" },
    },
  ];
  const edges: Edge[] = [
    edge("e1", "brief", "llm", "text", "text"),
    edge("e2", "llm", "t2i", "text", "prompt"),
    edge("e3", "product", "t2i", "image", "image"),
    edge("e4", "t2i", "i2v", "image", "image"),
    edge("e5", "llm", "i2v", "text", "prompt"),
    edge("e6", "llm", "tts", "narration", "text"),
    edge("e7", "i2v", "mix", "video", "video"),
    edge("e8", "tts", "mix", "audio", "vo"),
    edge("e9", "mix", "sub", "video", "video"),
    edge("e10", "brief", "sub", "text", "text"),
  ];
  return { nodes, edges };
}

export const WF_TEMPLATES: WfTemplate[] = [
  {
    id: "beauty_linear",
    name: "完整成片",
    hint: "从文案到口播、混音、字幕，一次搭好",
    kind: "beauty",
    build: beautyLinearGraph,
  },
  {
    id: "quick_shot",
    name: "快速出片",
    hint: "文案 → 出图 → 出视频，先出画面",
    kind: "beauty",
    build: quickShotGraph,
  },
  {
    id: "hardware_linear",
    name: "硬件成片",
    hint: "3C / 结构件主片：文案到口播、混音、字幕",
    kind: "hardware",
    build: hardwareLinearGraph,
  },
  {
    id: "hardware_lab",
    name: "工坊样机",
    hint: "对标科创学院：上传样机，工位氛围 + 口播成片",
    kind: "hardware",
    build: hardwareLabGraph,
  },
  {
    id: "hardware_quick",
    name: "硬件快测",
    hint: "工业风三步出画面，先看结构再补声音",
    kind: "hardware",
    build: hardwareQuickGraph,
  },
];
