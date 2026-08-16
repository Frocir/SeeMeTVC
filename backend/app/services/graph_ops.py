"""Canvas graph helpers for the in-process Agent MCP."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict, deque
from typing import Any

from app.services import seedance

# Match frontend/src/workflow/templates.ts grid.
LAYOUT_NODE_W = 300
LAYOUT_NODE_H = 320
LAYOUT_GAP_X = 140
LAYOUT_GAP_Y = 120
LAYOUT_ORIGIN_X = 64
LAYOUT_ORIGIN_Y = 64
LAYOUT_COL = LAYOUT_NODE_W + LAYOUT_GAP_X
LAYOUT_ROW = LAYOUT_NODE_H + LAYOUT_GAP_Y
LAYOUT_WRAP = 4
LAYOUT_COMPONENT_GAP = 80

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
        "ImageCompare",
        "SpeechToText",
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
    "ImageCompare": ("before", "image"),
    "SpeechToText": ("media", "text"),
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
            "label": "文案",
            "textRole": "brief",
            "brand": "GlamPilot",
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
        return {"nodeType": "AudioAsset", "label": "配乐", "audio_url": ""}
    if nt == "TextToImage":
        return {"nodeType": "TextToImage", "label": "出图", "model_id": ""}
    if nt == "ImageToVideo":
        return {
            "nodeType": "ImageToVideo",
            "label": "出视频",
            "duration_seconds": 5,
            "model_id": seedance.DEFAULT_VIDEO_MODEL_ID,
        }
    if nt == "VideoTrim":
        return {"nodeType": "VideoTrim", "label": "裁视频", "trim_start": 0, "trim_end": 5}
    if nt == "VideoMux":
        return {"nodeType": "VideoMux", "label": "拼接", "aspect": "16:9"}
    if nt == "MixAudio":
        return {"nodeType": "MixAudio", "label": "混音"}
    if nt == "VideoDemux":
        return {"nodeType": "VideoDemux", "label": "拆声音"}
    if nt == "VideoReversePrompt":
        return {
            "nodeType": "VideoReversePrompt",
            "label": "拆参考片",
            "frame_count": 3,
            "frame_strategy": "scene_detect",
            "max_scenes": 6,
            "scene_threshold": 0.28,
            "sample_fps": 2,
            "prompt_style": "seedance",
            "prompt": "",
        }
    if nt == "ImageCompare":
        return {
            "nodeType": "ImageCompare",
            "label": "对比图",
            "compare_mode": "slider",
            "selected": "after",
        }
    if nt == "SpeechToText":
        return {
            "nodeType": "SpeechToText",
            "label": "听写",
            "language": "zh",
            "model_id": "",
            "text": "",
            "srt": "",
        }
    if nt == "AudioTrim":
        return {"nodeType": "AudioTrim", "label": "裁音频", "trim_start": 0, "trim_end": 0}
    if nt == "SubtitleBurn":
        return {"nodeType": "SubtitleBurn", "label": "加字幕", "text": ""}
    if nt == "TtsSpeak":
        return {
            "nodeType": "TtsSpeak",
            "label": "配音",
            "model_id": "tts-1",
            "voice": "zh-CN-XiaoxiaoNeural",
            "text": "",
        }
    if nt == "LlmText":
        return {
            "nodeType": "LlmText",
            "label": "写镜头",
            "llmRole": "shot",
            "system_prompt": LLM_SYSTEM["shot"],
            "model_id": "",
            "wantNarration": True,
            "prompt": "",
            "text": "",
        }
    return {"nodeType": "TextAsset", "label": nt or "文案"}


def new_node_id() -> str:
    return "a" + uuid.uuid4().hex[:10]


def graph_summary(graph: dict, *, selected_id: str = "") -> str:
    lines: list[str] = []
    last_err = ""
    typed: dict[str, int] = defaultdict(int)
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict)]
    for n in nodes:
        nid = str(n.get("id") or "")
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        nt = normalize_type(n)
        typed[nt] += 1
        label = str(data.get("label") or nt)
        err = str(data.get("runError") or "")
        st = str(data.get("runStatus") or "")
        extra = f" [{st}]" if st else ""
        lines.append(f"- {nid} {nt} 「{label}」{extra}")
        if err:
            last_err = f"{label}: {err[:160]}"
    if len(nodes) > 20:
        counts = "、".join(f"{k}×{v}" for k, v in sorted(typed.items()))
        head = lines[:8]
        tail = lines[-4:] if len(lines) > 12 else []
        body = (
            f"共 {len(nodes)} 个节点，已经过多，禁止再批量 add_node。类型：{counts}\n"
            + "\n".join(head)
            + ("\n- …\n" + "\n".join(tail) if tail else "")
        )
    else:
        body = "\n".join(lines) if lines else "（空画布）"
    elines: list[str] = []
    for e in graph.get("edges") or []:
        if not isinstance(e, dict):
            continue
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if not src or not tgt:
            continue
        sh = str(e.get("sourceHandle") or "")
        th = str(e.get("targetHandle") or "")
        elines.append(f"- {src}:{sh} → {tgt}:{th}" if sh or th else f"- {src} → {tgt}")
    if len(elines) > 24:
        edges_body = f"共 {len(elines)} 条连线\n" + "\n".join(elines[:12]) + "\n- …"
    else:
        edges_body = "\n".join(elines) if elines else "（无连线）"
    sel = selected_id.strip() or "无"
    err_line = last_err or "无"
    return f"节点:\n{body}\n连线:\n{edges_body}\n选中: {sel}\n最近错误: {err_line}"


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


def layout_graph(graph: dict, *, direction: str = "horizontal") -> int:
    """Sugiyama layout: dummy vertices, barycenter crossing reduction, densest layer first."""
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, dict) and n.get("id") is not None]
    if not nodes:
        return 0
    id_to_node = {str(n.get("id")): n for n in nodes}
    ids = list(id_to_node.keys())
    order = {nid: i for i, nid in enumerate(ids)}
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    for e in graph.get("edges") or []:
        if not isinstance(e, dict):
            continue
        src, tgt = str(e.get("source") or ""), str(e.get("target") or "")
        if src in id_to_node and tgt in id_to_node and src != tgt:
            if tgt not in outgoing[src]:
                outgoing[src].append(tgt)
            if src not in incoming[tgt]:
                incoming[tgt].append(src)
    components: list[list[str]] = []
    seen: set[str] = set()
    for nid in ids:
        if nid in seen:
            continue
        stack = [nid]
        comp: list[str] = []
        seen.add(nid)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in list(outgoing[cur]) + list(incoming[cur]):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        comp.sort(key=lambda x: order[x])
        components.append(comp)

    horizontal = direction != "vertical"
    positions: dict[str, dict[str, float]] = {}
    offset = LAYOUT_ORIGIN_Y
    for comp in components:
        local = _layout_component(comp, outgoing, incoming, order, horizontal)
        min_y = min(p["y"] for p in (local[i] for i in comp))
        max_y = max(p["y"] for p in (local[i] for i in comp))
        shift = offset - min_y
        for nid in comp:
            p = local[nid]
            positions[nid] = {"x": p["x"], "y": p["y"] + shift}
        offset = max_y + shift + LAYOUT_ROW + LAYOUT_COMPONENT_GAP

    moved = 0
    for nid, node in id_to_node.items():
        pos = positions[nid]
        old = node.get("position") if isinstance(node.get("position"), dict) else {}
        if float(old.get("x") or 0) != pos["x"] or float(old.get("y") or 0) != pos["y"]:
            moved += 1
        node["position"] = pos
    return moved


def _layout_component(
    ids: list[str],
    outgoing: dict[str, list[str]],
    incoming: dict[str, list[str]],
    order: dict[str, int],
    horizontal: bool,
) -> dict[str, dict[str, float]]:
    def in_comp(nid: str, lst: list[str]) -> list[str]:
        return [x for x in lst if x in id_set]

    id_set = set(ids)
    positions: dict[str, dict[str, float]] = {}
    has_edge = any(in_comp(nid, outgoing[nid]) for nid in ids)
    if not has_edge:
        for i, nid in enumerate(ids):
            col, row = i % LAYOUT_WRAP, i // LAYOUT_WRAP
            positions[nid] = _xy(col, row, horizontal)
        return positions

    rank = _assign_ranks(ids, outgoing, incoming)
    for nid in ids:
        preds = in_comp(nid, incoming[nid])
        succs = in_comp(nid, outgoing[nid])
        if preds or not succs:
            continue
        rank[nid] = max(0, min(rank[s] for s in succs) - 1)

    used = sorted(set(rank.values()))
    remap = {r: i for i, r in enumerate(used)}
    for nid in list(rank):
        rank[nid] = remap[rank[nid]]

    proper_ids, out, inn, dummies = _insert_dummies(ids, outgoing, incoming, rank)
    layers = _build_layers(proper_ids, rank, dummies, order)
    ranks = sorted(layers)
    _reduce_crossings(layers, ranks, out, inn)
    row = _assign_rows(layers, ranks, out, inn, dummies)
    _place(positions, ids, rank, row, horizontal)
    return positions


def _xy(col: float, row: float, horizontal: bool) -> dict[str, float]:
    if horizontal:
        return {
            "x": float(LAYOUT_ORIGIN_X + col * LAYOUT_COL),
            "y": float(LAYOUT_ORIGIN_Y + row * LAYOUT_ROW),
        }
    return {
        "x": float(LAYOUT_ORIGIN_X + row * LAYOUT_COL),
        "y": float(LAYOUT_ORIGIN_Y + col * LAYOUT_ROW),
    }


def _assign_ranks(
    ids: list[str],
    outgoing: dict[str, list[str]],
    incoming: dict[str, list[str]],
) -> dict[str, int]:
    id_set = set(ids)
    remaining = {nid: len([p for p in incoming[nid] if p in id_set]) for nid in ids}
    rank = {nid: 0 for nid in ids}
    queue = deque([nid for nid in ids if remaining[nid] == 0])
    seen = 0
    while queue:
        nid = queue.popleft()
        seen += 1
        for tgt in outgoing[nid]:
            if tgt not in id_set:
                continue
            rank[tgt] = max(rank[tgt], rank[nid] + 1)
            remaining[tgt] -= 1
            if remaining[tgt] == 0:
                queue.append(tgt)
    if seen < len(ids):
        done_max = max((rank[nid] for nid in ids if remaining[nid] <= 0), default=0)
        for nid in ids:
            if remaining[nid] <= 0:
                continue
            preds = [rank[p] for p in incoming[nid] if p in id_set and remaining[p] <= 0]
            rank[nid] = (max(preds) + 1) if preds else done_max + 1
    return rank


def _link(out: dict[str, list[str]], inn: dict[str, list[str]], src: str, tgt: str) -> None:
    if tgt not in out[src]:
        out[src].append(tgt)
    if src not in inn[tgt]:
        inn[tgt].append(src)


def _unlink(out: dict[str, list[str]], inn: dict[str, list[str]], src: str, tgt: str) -> None:
    if tgt in out[src]:
        out[src].remove(tgt)
    if src in inn[tgt]:
        inn[tgt].remove(src)


def _insert_dummies(
    ids: list[str],
    outgoing: dict[str, list[str]],
    incoming: dict[str, list[str]],
    rank: dict[str, int],
) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]], set[str]]:
    id_set = set(ids)
    out: dict[str, list[str]] = defaultdict(list)
    inn: dict[str, list[str]] = defaultdict(list)
    for src in ids:
        for tgt in outgoing[src]:
            if tgt in id_set:
                _link(out, inn, src, tgt)
    dummies: set[str] = set()
    longs = [
        (src, tgt)
        for src in ids
        for tgt in list(out[src])
        if rank[tgt] - rank[src] > 1
    ]
    n = 0
    for src, tgt in longs:
        _unlink(out, inn, src, tgt)
        prev = src
        for r in range(rank[src] + 1, rank[tgt]):
            dummy = f"__d{n}"
            n += 1
            dummies.add(dummy)
            rank[dummy] = r
            _link(out, inn, prev, dummy)
            prev = dummy
        _link(out, inn, prev, tgt)
    return [*ids, *dummies], out, inn, dummies


def _build_layers(
    ids: list[str],
    rank: dict[str, int],
    dummies: set[str],
    order: dict[str, int],
) -> dict[int, list[str]]:
    layers: dict[int, list[str]] = defaultdict(list)
    for nid in ids:
        layers[rank[nid]].append(nid)
    for lst in layers.values():
        lst.sort(key=lambda x: (x in dummies, order.get(x, 0)))
    return layers


def _pos_map(layer: list[str]) -> dict[str, int]:
    return {nid: i for i, nid in enumerate(layer)}


def _barycenter(nid: str, neighbors: list[str], pos: dict[str, int], fallback: float) -> float:
    vals = [pos[n] for n in neighbors if n in pos]
    if not vals:
        return fallback
    return sum(vals) / len(vals)


def _count_pair_crossings(left: list[str], right: list[str], out: dict[str, list[str]]) -> int:
    right_pos = _pos_map(right)
    edges = [
        (i, right_pos[tgt])
        for i, src in enumerate(left)
        for tgt in out[src]
        if tgt in right_pos
    ]
    crosses = 0
    for i, (a0, a1) in enumerate(edges):
        for b0, b1 in edges[i + 1 :]:
            if (a0 - b0) * (a1 - b1) < 0:
                crosses += 1
    return crosses


def _count_crossings(layers: dict[int, list[str]], ranks: list[int], out: dict[str, list[str]]) -> int:
    return sum(
        _count_pair_crossings(layers[ranks[i]], layers[ranks[i + 1]], out)
        for i in range(len(ranks) - 1)
    )


def _sort_by_barycenter(layer: list[str], neighbor_pos: dict[str, int], adj: dict[str, list[str]]) -> None:
    keyed = [
        (_barycenter(nid, adj[nid], neighbor_pos, float(i)), i, nid) for i, nid in enumerate(layer)
    ]
    keyed.sort()
    layer[:] = [nid for _, _, nid in keyed]


def _adjacent_crossings(
    layers: dict[int, list[str]], ranks: list[int], idx: int, out: dict[str, list[str]]
) -> int:
    n = 0
    if idx > 0:
        n += _count_pair_crossings(layers[ranks[idx - 1]], layers[ranks[idx]], out)
    if idx < len(ranks) - 1:
        n += _count_pair_crossings(layers[ranks[idx]], layers[ranks[idx + 1]], out)
    return n


def _transpose(layers: dict[int, list[str]], ranks: list[int], out: dict[str, list[str]]) -> None:
    for _ in range(16):
        improved = False
        for idx, r in enumerate(ranks):
            layer = layers[r]
            for i in range(len(layer) - 1):
                before = _adjacent_crossings(layers, ranks, idx, out)
                layer[i], layer[i + 1] = layer[i + 1], layer[i]
                after = _adjacent_crossings(layers, ranks, idx, out)
                if after < before:
                    improved = True
                else:
                    layer[i], layer[i + 1] = layer[i + 1], layer[i]
        if not improved:
            break


def _reduce_crossings(
    layers: dict[int, list[str]],
    ranks: list[int],
    out: dict[str, list[str]],
    inn: dict[str, list[str]],
) -> None:
    best = {r: list(layers[r]) for r in ranks}
    best_x = _count_crossings(layers, ranks, out)
    if best_x == 0:
        return
    for pass_i in range(8):
        if pass_i % 2 == 0:
            for i in range(1, len(ranks)):
                _sort_by_barycenter(layers[ranks[i]], _pos_map(layers[ranks[i - 1]]), inn)
        else:
            for i in range(len(ranks) - 2, -1, -1):
                _sort_by_barycenter(layers[ranks[i]], _pos_map(layers[ranks[i + 1]]), out)
        _transpose(layers, ranks, out)
        x = _count_crossings(layers, ranks, out)
        if x < best_x:
            best = {r: list(layers[r]) for r in ranks}
            best_x = x
            if x == 0:
                break
    for r in ranks:
        layers[r][:] = best[r]


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    mid = (len(s) - 1) // 2
    return s[mid] if len(s) % 2 else (s[mid] + s[mid + 1]) / 2


def _place_compact_column(
    ids: list[str],
    row: dict[str, float],
    out: dict[str, list[str]],
    inn: dict[str, list[str]],
    dummies: set[str],
) -> None:
    desired: list[float] = []
    for nid in ids:
        neigh = [row[n] for n in list(inn[nid]) + list(out[nid]) if n in row and n not in dummies]
        desired.append(_median(neigh) if neigh else 0.0)
    start = round(_median(desired) - (len(ids) - 1) / 2)
    for i, nid in enumerate(ids):
        row[nid] = float(start + i)


def _assign_rows(
    layers: dict[int, list[str]],
    ranks: list[int],
    out: dict[str, list[str]],
    inn: dict[str, list[str]],
    dummies: set[str],
) -> dict[str, float]:
    real = {r: [nid for nid in layers[r] if nid not in dummies] for r in ranks}
    real = {r: lst for r, lst in real.items() if lst}
    cols = sorted(real)
    pivot = cols[0] if cols else 0
    pivot_size = -1
    for r in cols:
        n = len(real[r])
        if n > pivot_size:
            pivot, pivot_size = r, n
    row = {nid: float(i) for i, nid in enumerate(real[pivot])}
    sweep = [r for r in cols if r > pivot] + [r for r in cols if r < pivot][::-1]
    for r in sweep:
        _place_compact_column(real[r], row, out, inn, dummies)
    for _ in range(2):
        for r in cols:
            if r == pivot:
                continue
            _place_compact_column(real[r], row, out, inn, dummies)
    return row


def _place(
    positions: dict[str, dict[str, float]],
    ids: list[str],
    rank: dict[str, int],
    row: dict[str, float],
    horizontal: bool,
) -> None:
    for nid in ids:
        positions[nid] = _xy(rank[nid], row[nid], horizontal)


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
    data["runOutput"] = out
    for key in (
        "prompt",
        "text",
        "srt",
        "narration",
        "image_url",
        "before_url",
        "after_url",
        "url",
        "selected",
        "audio_url",
        "clip_url",
        "result_url",
        "preview_url",
    ):
        val = out.get(key)
        if isinstance(val, str) and val.strip():
            data[key] = val.strip()
    for key in ("scenes", "frames", "timeline", "segments"):
        if key in out and out[key] is not None:
            data[key] = out[key]
    if isinstance(out.get("clips"), list) and out["clips"] and isinstance(out["clips"][0], str):
        data["clip_url"] = out["clips"][0]
        data["preview_url"] = out["clips"][0]
    node["data"] = data


def _find(graph: dict, node_id: str) -> dict:
    for n in graph.get("nodes") or []:
        if isinstance(n, dict) and str(n.get("id")) == node_id:
            return n
    raise ValueError(f"节点不存在：{node_id}")
