import type { Edge, Node } from "@xyflow/react";
import type { PaletteItem, WfData, WfNodeType } from "./types";

export const PALETTE: PaletteItem[] = [
  { type: "TextAsset", label: "文本", hint: "Brief / 剧本 / 提示词" },
  { type: "ImageAsset", label: "图片", hint: "上传或参考图" },
  { type: "VideoAsset", label: "视频", hint: "上传或成片载体" },
  { type: "ImageToVideo", label: "图生视频", hint: "一镜一段，结果写在本节点" },
  { type: "VideoTrim", label: "裁时长", hint: "ffmpeg trim" },
  { type: "VideoMux", label: "真拼接", hint: "ffmpeg 合成" },
];

export function defaultData(type: WfNodeType, modelId = ""): WfData {
  const label = PALETTE.find((p) => p.type === type)?.label || type;
  switch (type) {
    case "TextAsset":
    case "BriefInput":
      return {
        nodeType: "TextAsset",
        label: type === "BriefInput" ? "文案" : label,
        textRole: "brief",
        brand: "SeeMe",
        selling_points: "水光肌、持妆、气色",
        slogan: "看见更好的自己",
        prompt: "高端美妆广告短片，柔光特写",
        text: "",
      };
    case "ScenePlan":
      return {
        nodeType: "TextAsset",
        label: "剧本",
        textRole: "script",
        scene_count: 3,
        prompt: "",
      };
    case "ImageAsset":
    case "MakeupControl":
      return {
        nodeType: "ImageAsset",
        label: type === "MakeupControl" ? "妆造" : label,
        intensity: 0.7,
        before_prompt: "素颜自然肤质",
        after_prompt: "精致妆容，气色明亮",
      };
    case "VideoAsset":
    case "PreviewOut":
      return { nodeType: "VideoAsset", label: type === "PreviewOut" ? "成片" : label };
    case "ImageToVideo":
    case "ShotGenerate":
      return {
        nodeType: "ImageToVideo",
        label: type === "ShotGenerate" ? "视频" : label,
        model_id: modelId,
        duration_seconds: 5,
        use_scenes: true,
        max_shots: 1,
      };
    case "VideoTrim":
      return {
        nodeType: "VideoTrim",
        label,
        trim_start: 0,
        trim_end: 4,
      };
    case "VideoMux":
    case "TimelineMux":
      return {
        nodeType: "VideoMux",
        label: type === "TimelineMux" ? "拼接" : label,
        aspect: "16:9",
        pick: "first",
      };
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

export type WfTemplateId = "beauty_linear" | "standard" | "quick_shot";

export type WfTemplate = {
  id: WfTemplateId;
  name: string;
  hint: string;
  build: (modelId: string) => { nodes: Node<WfData>[]; edges: Edge[] };
};

/** Official beauty linear chain (Q26=A). */
export function defaultGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  return beautyLinearGraph(modelId);
}

/** Layout grid sized for cv-node (~300×~320 including chrome). */
const NODE_W = 300;
const NODE_H = 320;
const GAP_X = 140;
const GAP_Y = 120;
const COL = NODE_W + GAP_X; // 440
const ROW = NODE_H + GAP_Y; // 440
const ORIGIN_X = 64;
const ORIGIN_Y = 64;

function at(col: number, row: number) {
  return { x: ORIGIN_X + col * COL, y: ORIGIN_Y + row * ROW };
}

function beautyLinearGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  // Row0: brief → script → shot → trim → mux → out
  // Row1 under script: makeup → (feeds shot)
  const nodes: Node<WfData>[] = [
    {
      id: "brief",
      type: "media",
      position: at(0, 0),
      data: { ...defaultData("TextAsset", modelId), label: "品牌 Brief", textRole: "brief" },
    },
    {
      id: "script",
      type: "media",
      position: at(1, 0),
      data: {
        ...defaultData("TextAsset", modelId),
        label: "剧本",
        textRole: "script",
        scene_count: 3,
        brand: undefined,
        selling_points: undefined,
        slogan: undefined,
        prompt: "",
      },
    },
    {
      id: "makeup",
      type: "media",
      position: at(1, 1),
      data: { ...defaultData("ImageAsset", modelId), label: "妆造图" },
    },
    {
      id: "shot",
      type: "media",
      position: at(2, 0),
      data: { ...defaultData("ImageToVideo", modelId), label: "图生视频", max_shots: 1 },
    },
    {
      id: "trim",
      type: "media",
      position: at(3, 0),
      data: { ...defaultData("VideoTrim", modelId), label: "裁时长", trim_start: 0, trim_end: 4 },
    },
    {
      id: "mux",
      type: "media",
      position: at(4, 0),
      data: { ...defaultData("VideoMux", modelId), label: "真拼接" },
    },
    {
      id: "out",
      type: "media",
      position: at(5, 0),
      data: { ...defaultData("VideoAsset", modelId), label: "成片" },
    },
  ];
  const edges: Edge[] = [
    edge("e1", "brief", "script", "text", "text"),
    edge("e2", "script", "shot", "text", "prompt"),
    edge("e3", "makeup", "shot", "image", "image"),
    edge("e4", "shot", "trim", "video", "video"),
    edge("e5", "trim", "mux", "video", "clips"),
    edge("e6", "shot", "mux", "clips", "clips"),
    edge("e7", "mux", "out", "video", "video"),
  ];
  return { nodes, edges };
}

/** Compat: old branched standard → freeform linear-ish */
function standardGraph(modelId: string): { nodes: Node<WfData>[]; edges: Edge[] } {
  return beautyLinearGraph(modelId);
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
      id: "makeup",
      type: "media",
      position: at(0, 1),
      data: { ...defaultData("ImageAsset", modelId), label: "参考图" },
    },
    {
      id: "shot",
      type: "media",
      position: at(1, 0),
      data: {
        ...defaultData("ImageToVideo", modelId),
        use_scenes: false,
        max_shots: 1,
      },
    },
    {
      id: "out",
      type: "media",
      position: at(2, 0),
      data: { ...defaultData("VideoAsset", modelId), label: "成片" },
    },
  ];
  const edges: Edge[] = [
    edge("e1", "brief", "shot", "text", "prompt"),
    edge("e2", "makeup", "shot", "image", "image"),
    edge("e3", "shot", "out", "video", "video"),
  ];
  return { nodes, edges };
}

export const WF_TEMPLATES: WfTemplate[] = [
  {
    id: "beauty_linear",
    name: "美妆线性链路",
    hint: "Brief → 剧本 → 妆造 → 图生视频(一镜) → trim → 拼接 → 成片",
    build: beautyLinearGraph,
  },
  {
    id: "standard",
    name: "标准美妆 TVC",
    hint: "同线性链路（图相同）；若刚跑过易触发 Agnes 限流",
    build: standardGraph,
  },
  {
    id: "quick_shot",
    name: "单镜头快出",
    hint: "Brief + 图 → 一镜成片",
    build: quickShotGraph,
  },
];
