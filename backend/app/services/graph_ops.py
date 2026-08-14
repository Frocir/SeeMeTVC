"""Canvas graph helpers for the in-process Agent MCP."""

from __future__ import annotations

import json
import uuid
from typing import Any

LEGACY_TO_FREE = {
    "BriefInput": "TextAsset",
    "ScenePlan": "TextAsset",
    "MakeupControl": "ImageAsset",
    "ShotGenerate": "ImageToVideo",
    "TimelineMux": "VideoMux",
    "PreviewOut": "VideoAsset",
    "LlmChat": "LlmText",
    "LlmBrief": "LlmText",
    "LlmStoryboard": "LlmText",
    "LlmShot": "LlmText",
}

NODE_TYPES = frozenset(
    {
        "TextAsset",
        "ImageAsset",
        "VideoAsset",
        "AudioAsset",
        "LlmText",
        "TextToImage",
        "ImageToVideo",
        "VideoTrim",
        "VideoMux",
        "MixAudio",
        "VideoDemux",
        "VideoReversePrompt",
        "AudioTrim",
        "TtsSpeak",
        "SubtitleBurn",
        *LEGACY_TO_FREE.keys(),
    }
)

LLM_SYSTEM = {
    "chat": "",
    "brief": (
        "你是美妆 TVC 文案。根据用户给出的品牌、卖点、口号，写一段可直接给下游使用的 Brief。"
        "只输出正文，不要标题或 Markdown。"
    ),
    "shot": (
        "你是美妆广告单镜写手。根据 Brief 只写一镜。输出严格 JSON（不要 Markdown 围栏）："
        '{"prompt":"该镜的画面提示词","narration":"一句适合口播的中文旁白，约 15–40 字"}。'
        "禁止 scenes 数组，禁止多镜。"
    ),
}

PORT_DEFAULTS: dict[str, tuple[str, str]] = {
    "TextAsset": ("text", "text"),
    "ImageAsset": ("image", "image"),
    "VideoAsset": ("video", "video"),
    "AudioAsset": ("audio", "audio"),
    "LlmText": ("text", "text"),
    "TextToImage": ("prompt", "image"),
    "ImageToVideo": ("image", "video"),
    "VideoTrim": ("video", "video"),
    "VideoMux": ("video", "video"),
    "MixAudio": ("video", "video"),
    "VideoDemux": ("video", "video"),
    "VideoReversePrompt": ("video", "text"),
    "AudioTrim": ("audio", "audio"),
    "TtsSpeak": ("text", "audio"),
    "SubtitleBurn": ("video", "video"),
}


def parse_graph(raw: str | dict | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        data = dict(raw)
    else:
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
    data.setdefault("nodes", [])
    data.setdefault("edges", [])
    data.pop("__run_opts__", None)
    return data


def normalize_type(node: dict) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    raw = str(node.get("type") or data.get("nodeType") or "TextAsset")
    if raw in {"wf", "media"}:
        raw = str(data.get("nodeType") or "TextAsset")
    return LEGACY_TO_FREE.get(raw, raw)


def default_data(node_type: str) -> dict[str, Any]:
    nt = LEGACY_TO_FREE.get(node_type, node_type)
    if nt == "TextAsset":
        return {
            "nodeType": "TextAsset",
            "label": "文本",
            "textRole": "brief",
            "brand": "SeeMe",
            "selling_points": "水光肌、持妆、气色",
            "slogan": "看见更好的自己",
            "prompt": "高端美妆广告短片，柔光特写",
            "text": "",
        }
    if nt == "ImageAsset":
        return {"nodeType": "ImageAsset", "label": "图片"}
    if nt == "VideoAsset":
        return {"nodeType": "VideoAsset", "label": "视频"}
    if nt == "AudioAsset":
        return {"nodeType": "AudioAsset", "label": "音频", "audio_url": ""}
    if nt == "TextToImage":
        return {"nodeType": "TextToImage", "label": "文生图", "model_id": "t2i-local-simulate"}
    if nt == "ImageToVideo":
        return {"nodeType": "ImageToVideo", "label": "图生视频", "duration_seconds": 5}
    if nt == "VideoTrim":
        return {"nodeType": "VideoTrim", "label": "裁时长", "trim_start": 0, "trim_end": 5}
    if nt == "VideoMux":
        return {"nodeType": "VideoMux", "label": "真拼接", "aspect": "16:9"}
    if nt == "MixAudio":
        return {"nodeType": "MixAudio", "label": "混音"}
    if nt == "VideoDemux":
        return {"nodeType": "VideoDemux", "label": "拆音轨"}
    if nt == "VideoReversePrompt":
        return {
            "nodeType": "VideoReversePrompt",
            "label": "视频反推",
            "frame_count": 3,
            "frame_strategy": "scene_detect",
            "max_scenes": 6,
            "scene_threshold": 0.28,
            "sample_fps": 2,
            "prompt_style": "seedance",
            "prompt": "",
        }
    if nt == "AudioTrim":
        return {"nodeType": "AudioTrim", "label": "音频裁切", "trim_start": 0, "trim_end": 0}
    if nt == "SubtitleBurn":
        return {"nodeType": "SubtitleBurn", "label": "字幕", "text": ""}
    if nt == "TtsSpeak":
        return {
            "nodeType": "TtsSpeak",
            "label": "TTS 口播",
            "model_id": "tts-1",
            "voice": "zh-CN-XiaoxiaoNeural",
            "text": "",
        }
    if nt == "LlmText":
        return {
            "nodeType": "LlmText",
            "label": "LLM",
            "llmRole": "shot",
            "system_prompt": LLM_SYSTEM["shot"],
            "model_id": "llm-local-simulate",
            "wantNarration": True,
            "prompt": "",
            "text": "",
        }
    return {"nodeType": "TextAsset", "label": nt or "文本"}


def new_node_id() -> str:
    return "a" + uuid.uuid4().hex[:10]


def graph_summary(graph: dict, *, selected_id: str = "") -> str:
    lines: list[str] = []
    last_err = ""
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "")
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        nt = normalize_type(n)
        label = str(data.get("label") or nt)
        err = str(data.get("runError") or "")
        st = str(data.get("runStatus") or "")
        extra = f" [{st}]" if st else ""
        lines.append(f"- {nid} {nt} 「{label}」{extra}")
        if err:
            last_err = f"{label}: {err[:160]}"
    body = "\n".join(lines) if lines else "（空画布）"
    sel = selected_id.strip() or "无"
    err_line = last_err or "无"
    return f"节点:\n{body}\n选中: {sel}\n最近错误: {err_line}"


def slim_graph(graph: dict) -> dict:
    nodes = []
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        slim = {
            "id": n.get("id"),
            "type": normalize_type(n),
            "label": data.get("label"),
            "position": n.get("position"),
            "llmRole": data.get("llmRole"),
            "textRole": data.get("textRole"),
            "model_id": data.get("model_id"),
            "prompt": _clip(data.get("prompt") or data.get("text")),
            "runStatus": data.get("runStatus"),
            "runError": _clip(data.get("runError"), 200),
            "has_image": bool(data.get("image_url")),
            "has_video": bool(data.get("clip_url") or data.get("result_url")),
            "has_audio": bool(data.get("audio_url")),
        }
        nodes.append(slim)
    edges = []
    for e in graph.get("edges") or []:
        if not isinstance(e, dict):
            continue
        edges.append(
            {
                "id": e.get("id"),
                "source": e.get("source"),
                "target": e.get("target"),
                "sourceHandle": e.get("sourceHandle"),
                "targetHandle": e.get("targetHandle"),
            }
        )
    return {"nodes": nodes, "edges": edges}


def _clip(val: Any, n: int = 240) -> str:
    s = str(val or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def add_node(
    graph: dict,
    *,
    node_type: str,
    label: str = "",
    data: dict | None = None,
    x: float | None = None,
    y: float | None = None,
    viewport: tuple[float, float] = (400.0, 280.0),
) -> str:
    nt = LEGACY_TO_FREE.get(node_type, node_type)
    if nt not in NODE_TYPES and nt not in LEGACY_TO_FREE.values():
        raise ValueError(f"未知节点类型：{node_type}")
    nid = new_node_id()
    count = len(graph.get("nodes") or [])
    ox, oy = viewport
    pos = {
        "x": float(x if x is not None else ox + 40 * (count % 8)),
        "y": float(y if y is not None else oy + 40 * (count % 8)),
    }
    payload = default_data(nt)
    if data:
        payload.update({k: v for k, v in data.items() if v is not None})
    payload["nodeType"] = nt
    if label.strip():
        payload["label"] = label.strip()
    graph.setdefault("nodes", []).append({"id": nid, "type": nt, "position": pos, "data": payload})
    return nid


def patch_node(
    graph: dict,
    node_id: str,
    *,
    data: dict | None = None,
    label: str | None = None,
    x: float | None = None,
    y: float | None = None,
) -> None:
    node = _find(graph, node_id)
    cur = node.get("data") if isinstance(node.get("data"), dict) else {}
    if data:
        cur = {**cur, **data}
    if label is not None:
        cur["label"] = label
    node["data"] = cur
    if x is not None or y is not None:
        pos = dict(node.get("position") or {})
        if x is not None:
            pos["x"] = float(x)
        if y is not None:
            pos["y"] = float(y)
        node["position"] = pos


def delete_node(graph: dict, node_id: str) -> None:
    _find(graph, node_id)
    graph["nodes"] = [n for n in graph.get("nodes") or [] if str(n.get("id")) != node_id]
    graph["edges"] = [
        e
        for e in graph.get("edges") or []
        if str(e.get("source")) != node_id and str(e.get("target")) != node_id
    ]


def connect(
    graph: dict,
    *,
    source: str,
    target: str,
    source_handle: str = "",
    target_handle: str = "",
) -> str:
    if source == target:
        raise ValueError("不能连接自己")
    src = _find(graph, source)
    tgt = _find(graph, target)
    from app.services.node_contracts import resolve_connect_handles, validate_connect

    types = {str(n.get("id")): normalize_type(n) for n in graph.get("nodes") or [] if n.get("id") is not None}
    sh, th = resolve_connect_handles(
        normalize_type(src),
        normalize_type(tgt),
        source_handle,
        target_handle,
    )
    validate_connect(
        source_id=source,
        source_type=normalize_type(src),
        target_type=normalize_type(tgt),
        source_handle=sh,
        target_handle=th,
        edges=list(graph.get("edges") or []),
        types=types,
    )
    for e in graph.get("edges") or []:
        if (
            str(e.get("source")) == source
            and str(e.get("target")) == target
            and str(e.get("sourceHandle") or "") == sh
            and str(e.get("targetHandle") or "") == th
        ):
            return str(e.get("id") or "")
    eid = "e" + uuid.uuid4().hex[:10]
    graph.setdefault("edges", []).append(
        {"id": eid, "source": source, "target": target, "sourceHandle": sh, "targetHandle": th}
    )
    return eid


def apply_run_output(graph: dict, node_id: str, output: dict | None, status: str, error: str = "") -> None:
    node = _find(graph, node_id)
    data = dict(node.get("data") or {})
    data["runStatus"] = status
    data["runError"] = error or None
    out = output or {}
    for key in (
        "prompt",
        "text",
        "narration",
        "image_url",
        "audio_url",
        "clip_url",
        "result_url",
        "preview_url",
    ):
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            data[key] = val.strip()
    if isinstance(out.get("clips"), list) and out["clips"] and isinstance(out["clips"][0], str):
        data["clip_url"] = out["clips"][0]
        data["preview_url"] = out["clips"][0]
    node["data"] = data


def _find(graph: dict, node_id: str) -> dict:
    for n in graph.get("nodes") or []:
        if isinstance(n, dict) and str(n.get("id")) == node_id:
            return n
    raise ValueError(f"节点不存在：{node_id}")
