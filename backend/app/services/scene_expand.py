"""Expand reverse-prompt scenes into executable workflow node chains."""

from __future__ import annotations

from typing import Any

from app.services import graph_ops

NODE_W = 320
GAP_X = 170
GAP_Y = 230


def _node_data(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = graph_ops._find(graph, node_id)
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return data


def _node_pos(graph: dict[str, Any], node_id: str) -> dict[str, float]:
    node = graph_ops._find(graph, node_id)
    pos = node.get("position") if isinstance(node.get("position"), dict) else {}
    return {"x": float(pos.get("x") or 0), "y": float(pos.get("y") or 0)}


def _scene_prompt(scene: dict[str, Any], idx: int) -> str:
    prompt = str(scene.get("prompt") or scene.get("seedance_prompt") or "").strip()
    if prompt:
        return prompt
    title = str(scene.get("title") or f"Clip {idx:02d}")
    return f"{title}，美妆产品广告单镜，柔和棚拍光，突出产品质地，不要字幕、水印或无关文字。"


def _scene_narration(scene: dict[str, Any]) -> str:
    return str(scene.get("narration") or "").strip()


def _edge(graph: dict[str, Any], source: str, target: str, source_handle: str, target_handle: str) -> str:
    return graph_ops.connect(
        graph,
        source=source,
        target=target,
        source_handle=source_handle,
        target_handle=target_handle,
    )


def expand_scenes_to_nodes(
    graph: dict[str, Any],
    *,
    source_node_id: str,
    mode: str = "with_image",
    create_images: bool | None = None,
    create_tts: bool | None = None,
    create_subtitles: bool | None = None,
    layout: str = "horizontal",
) -> dict[str, Any]:
    data = _node_data(graph, source_node_id)
    raw_scenes = data.get("scenes") or (data.get("runOutput") or {}).get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("视频反推节点没有可展开的 scenes，请先运行反推节点")

    valid_scenes = [s for s in raw_scenes if isinstance(s, dict)]
    source_scene_count = len(valid_scenes)
    scenes = valid_scenes[:8]
    if not scenes:
        raise ValueError("视频反推 scenes 格式无效")

    mode = (mode or "with_image").strip()
    if create_images is None:
        create_images = mode in {"with_image", "full_tvc"}
    if create_tts is None:
        create_tts = mode in {"with_tts", "full_tvc"}
    if create_subtitles is None:
        create_subtitles = mode == "full_tvc"

    origin = _node_pos(graph, source_node_id)
    base_x = origin["x"] + NODE_W + GAP_X
    base_y = origin["y"]
    horizontal = layout != "vertical"

    created_nodes: list[str] = []
    created_edges: list[str] = []
    clip_nodes: list[str] = []
    tts_nodes: list[str] = []

    for idx, scene in enumerate(scenes, start=1):
        row_y = base_y + (idx - 1) * GAP_Y
        col_x = base_x
        if not horizontal:
            row_y = base_y
            col_x = base_x + (idx - 1) * (NODE_W + GAP_X)

        title = str(scene.get("title") or f"Clip {idx:02d}")
        prompt = _scene_prompt(scene, idx)
        narration = _scene_narration(scene)
        prompt_id = graph_ops.add_node(
            graph,
            node_type="TextAsset",
            label=f"{title} · Prompt",
            data={
                "textRole": "prompt",
                "prompt": prompt,
                "text": prompt,
                "source_reverse_node_id": source_node_id,
                "source_scene_id": scene.get("id") or f"scene_{idx:03d}",
            },
            x=col_x,
            y=row_y,
        )
        created_nodes.append(prompt_id)

        current_prompt_source = prompt_id
        current_image_source = ""
        next_x = col_x + NODE_W + GAP_X

        if create_images:
            image_id = graph_ops.add_node(
                graph,
                node_type="TextToImage",
                label=f"{title} · 首帧",
                data={
                    "prompt": prompt,
                    "text": prompt,
                    "source_reverse_node_id": source_node_id,
                    "source_scene_id": scene.get("id") or f"scene_{idx:03d}",
                },
                x=next_x,
                y=row_y,
            )
            created_nodes.append(image_id)
            created_edges.append(_edge(graph, current_prompt_source, image_id, "text", "prompt"))
            current_image_source = image_id
            next_x += NODE_W + GAP_X

        video_id = graph_ops.add_node(
            graph,
            node_type="ImageToVideo",
            label=f"{title} · 视频",
            data={
                "prompt": prompt,
                "text": prompt,
                "duration_seconds": 5,
                "model_id": "seedance-2.5",
                "source_reverse_node_id": source_node_id,
                "source_scene_id": scene.get("id") or f"scene_{idx:03d}",
            },
            x=next_x,
            y=row_y,
        )
        created_nodes.append(video_id)
        clip_nodes.append(video_id)
        created_edges.append(_edge(graph, current_prompt_source, video_id, "text", "prompt"))
        if current_image_source:
            created_edges.append(_edge(graph, current_image_source, video_id, "image", "image"))

        if create_tts and narration:
            tts_id = graph_ops.add_node(
                graph,
                node_type="TtsSpeak",
                label=f"{title} · 口播",
                data={
                    "text": narration,
                    "narration": narration,
                    "source_reverse_node_id": source_node_id,
                    "source_scene_id": scene.get("id") or f"scene_{idx:03d}",
                },
                x=next_x,
                y=row_y + 105,
            )
            created_nodes.append(tts_id)
            tts_nodes.append(tts_id)

    mux_x = base_x + (3 if create_images else 2) * (NODE_W + GAP_X)
    mux_y = base_y + ((len(scenes) - 1) * GAP_Y) / 2
    mux_id = graph_ops.add_node(
        graph,
        node_type="VideoMux",
        label="分镜拼接",
        data={"aspect": data.get("aspect") or "16:9", "source_reverse_node_id": source_node_id},
        x=mux_x,
        y=mux_y,
    )
    created_nodes.append(mux_id)
    for clip_id in clip_nodes:
        created_edges.append(_edge(graph, clip_id, mux_id, "video", "video"))

    final_node_id = mux_id
    if create_tts and tts_nodes:
        mix_id = graph_ops.add_node(
            graph,
            node_type="MixAudio",
            label="分镜混音",
            data={"source_reverse_node_id": source_node_id},
            x=mux_x + NODE_W + GAP_X,
            y=mux_y,
        )
        created_nodes.append(mix_id)
        created_edges.append(_edge(graph, mux_id, mix_id, "video", "video"))
        created_edges.append(_edge(graph, tts_nodes[0], mix_id, "audio", "vo"))
        final_node_id = mix_id

    if create_subtitles:
        sub_id = graph_ops.add_node(
            graph,
            node_type="SubtitleBurn",
            label="字幕成片",
            data={
                "text": str(data.get("slogan") or data.get("text") or "").strip(),
                "source_reverse_node_id": source_node_id,
            },
            x=mux_x + (2 if create_tts and tts_nodes else 1) * (NODE_W + GAP_X),
            y=mux_y,
        )
        created_nodes.append(sub_id)
        created_edges.append(_edge(graph, final_node_id, sub_id, "video", "video"))
        final_node_id = sub_id

    warning = ""
    if source_scene_count > 4:
        warning = f"分镜共 {source_scene_count} 条（已展开前 {len(scenes)} 条）。超过 4 条时应先询问用户是否压缩。"
    return {
        "graph": graph,
        "source_node_id": source_node_id,
        "mode": mode,
        "scene_count": len(scenes),
        "source_scene_count": source_scene_count,
        "created_node_ids": created_nodes,
        "created_edge_ids": created_edges,
        "final_node_id": final_node_id,
        "warning": warning or None,
    }
