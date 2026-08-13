"""Explain why a canvas graph cannot start a run (empty / no generatable nodes)."""

from __future__ import annotations

LEGACY_TO_FREE = {
    "BriefInput": "TextAsset",
    "ScenePlan": "TextAsset",
    "MakeupControl": "ImageAsset",
    "ShotGenerate": "ImageToVideo",
    "TimelineMux": "VideoMux",
    "PreviewOut": "VideoAsset",
}

EXIT_TYPES = {"ImageToVideo", "VideoTrim", "VideoMux", "ShotGenerate", "TimelineMux"}
RUNNABLE = EXIT_TYPES | {"VideoAsset", "PreviewOut"}


def _normalize_type(node: dict) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    raw = node.get("type") or data.get("nodeType") or data.get("type") or ""
    s = str(raw)
    return LEGACY_TO_FREE.get(s, s)


def cannot_run_reason(graph: dict | None, *, target_ids: list[str] | None = None) -> str | None:
    nodes = list((graph or {}).get("nodes") or [])
    if not nodes:
        return (
            "画布上没有节点，无法生成。请从左侧「节点」添加「图生视频」等节点，"
            "或用模板预填后再一键跑。"
        )
    targets = [str(x) for x in (target_ids or []) if x]
    if targets:
        ids = {str(n.get("id")) for n in nodes if n.get("id") is not None}
        if any(t not in ids for t in targets):
            return "选中的节点已不在画布上，无法生成。"
        return None
    if not any(_normalize_type(n) in RUNNABLE for n in nodes):
        return "没有可出片的节点。请添加「图生视频」「裁时长」或「真拼接」后再一键跑。"
    return None
