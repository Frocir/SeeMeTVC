"""Canvas run preflight driven by node_contracts.yaml."""

from __future__ import annotations

from collections import defaultdict, deque

from app.services.node_contracts import (
    forbid_edge_reason,
    is_exit_type,
    is_producer_type,
    load_contracts,
    needs_channel,
    node_spec,
    normalize_type_name,
    validate_connect,
)


def _data(node: dict | None) -> dict:
    if not node:
        return {}
    raw = node.get("data")
    return raw if isinstance(raw, dict) else {}


def _normalize_type(node: dict) -> str:
    data = _data(node)
    raw = node.get("type") or data.get("nodeType") or data.get("type") or ""
    return normalize_type_name(str(raw))


def _label(nid: str, types: dict[str, str], by_id: dict[str, dict]) -> str:
    spec = node_spec(types.get(nid) or "")
    return str(_data(by_id.get(nid)).get("label") or spec.get("label") or types.get(nid) or nid)


def _filled(data: dict, keys: list | None) -> bool:
    for k in keys or []:
        val = data.get(k)
        if isinstance(val, str) and val.strip():
            return True
    return False


def _incoming(node_id: str, edges: list[dict]) -> list[dict]:
    return [e for e in edges if str(e.get("target")) == node_id]


def _incoming_handles(node_id: str, edges: list[dict]) -> set[str]:
    found: set[str] = set()
    for e in _incoming(node_id, edges):
        h = str(e.get("targetHandle") or e.get("sourceHandle") or "")
        if h:
            found.add(h)
    return found


def _adj(edges: list[dict], id_set: set[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    down: dict[str, list[str]] = defaultdict(list)
    up: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        src, tgt = str(e.get("source")), str(e.get("target"))
        if src in id_set and tgt in id_set:
            down[src].append(tgt)
            up[tgt].append(src)
    return down, up


def _has_cycle(ids: list[str], down: dict[str, list[str]]) -> bool:
    indeg = {i: 0 for i in ids}
    for src, outs in down.items():
        if src not in indeg:
            continue
        for tgt in outs:
            if tgt in indeg:
                indeg[tgt] += 1
    q = deque([i for i, d in indeg.items() if d == 0])
    seen = 0
    while q:
        u = q.popleft()
        seen += 1
        for v in down.get(u, []):
            if v not in indeg:
                continue
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return seen != len(ids)


def _undirected_components(ids: list[str], edges: list[dict]) -> list[list[str]]:
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    id_set = set(ids)
    for e in edges:
        s, t = str(e.get("source")), str(e.get("target"))
        if s in id_set and t in id_set:
            union(s, t)
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _can_reach(start: str, goals: set[str], down: dict[str, list[str]]) -> bool:
    if start in goals:
        return True
    seen = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for v in down.get(u, []):
            if v in seen:
                continue
            if v in goals:
                return True
            seen.add(v)
            stack.append(v)
    return False


def _fmt(template: str, *, label: str, missing: str = "") -> str:
    return (template or "").replace("{label}", label).replace("{missing}", missing)


def _node_input_reason(
    nid: str,
    types: dict[str, str],
    by_id: dict[str, dict],
    edges: list[dict],
) -> str | None:
    ntype = types.get(nid) or ""
    spec = node_spec(ntype)
    if not spec:
        return None
    data = _data(by_id.get(nid))
    label = _label(nid, types, by_id)
    incoming = _incoming(nid, edges)
    handles = _incoming_handles(nid, edges)

    chain_fields = spec.get("in_chain_fields")
    if chain_fields and not _filled(data, list(chain_fields)) and not incoming:
        tmpl = str(spec.get("in_chain_missing") or "「{label}」缺少必要素材。")
        return _fmt(tmpl, label=label)

    missing_edges: list[str] = []
    edge_tmpl = ""
    for port in spec.get("inputs") or []:
        pid = str(port.get("id") or "")
        mode = str(port.get("required") or "optional")
        if mode == "optional":
            continue
        fields = list(port.get("fields") or spec.get("fields") or [])
        has_edge = pid in handles or (not pid and bool(incoming))
        has_fields = _filled(data, fields)
        if mode == "edge":
            if not has_edge:
                missing_edges.append(pid)
                edge_tmpl = str(port.get("missing") or edge_tmpl or "「{label}」缺少输入：{missing}。")
            src_fields = port.get("source_fields") if isinstance(port.get("source_fields"), dict) else {}
            if has_edge and src_fields:
                for e in incoming:
                    th = str(e.get("targetHandle") or "")
                    if th and th != pid:
                        continue
                    src = by_id.get(str(e.get("source")))
                    if src is None:
                        continue
                    st = _normalize_type(src)
                    need = src_fields.get(st)
                    if not need:
                        continue
                    if not _filled(_data(src), list(need)):
                        return str(
                            port.get("source_fields_missing")
                            or f"「{label}」的 {pid} 口所接节点缺少文件。"
                        )
            continue
        if mode == "edge_or_fields":
            if has_edge or has_fields:
                continue
            tmpl = str(port.get("missing") or "「{label}」缺少输入。")
            return _fmt(tmpl, label=label)
        if mode == "fields" and not has_fields:
            tmpl = str(port.get("missing") or "「{label}」缺少输入。")
            return _fmt(tmpl, label=label)
    if missing_edges:
        return _fmt(edge_tmpl, label=label, missing="、".join(missing_edges))
    return None


def _invalid_edge_reason(
    types: dict[str, str],
    by_id: dict[str, dict],
    edges: list[dict],
    check_ids: list[str],
) -> str | None:
    check = set(check_ids)
    for e in edges:
        src = str(e.get("source"))
        tgt = str(e.get("target"))
        if tgt not in check:
            continue
        if src not in by_id or tgt not in by_id:
            return "画布存在指向已删除节点的连线，请删除无效连线后再运行。"
        try:
            validate_connect(
                source_id=src,
                source_type=types.get(src) or "",
                target_type=types.get(tgt) or "",
                source_handle=str(e.get("sourceHandle") or ""),
                target_handle=str(e.get("targetHandle") or ""),
                edges=edges,
                types=types,
            )
        except ValueError as exc:
            return str(exc)
    return None


def _edge_forbid_reason(
    types: dict[str, str],
    by_id: dict[str, dict],
    edges: list[dict],
    check_ids: list[str],
) -> str | None:
    check = set(check_ids)
    for e in edges:
        tgt = str(e.get("target"))
        if tgt not in check:
            continue
        src = str(e.get("source"))
        msg = forbid_edge_reason(
            source_id=src,
            source_type=types.get(src) or "",
            target_type=types.get(tgt) or "",
            target_handle=str(e.get("targetHandle") or ""),
            edges=edges,
            types=types,
        )
        if msg:
            return msg
    return None


def cannot_run_reason(
    graph: dict | None,
    *,
    target_ids: list[str] | None = None,
    has_video_model: bool = True,
    has_llm_model: bool = True,
    has_tts_model: bool = True,
    has_image_model: bool = True,
) -> str | None:
    load_contracts()
    nodes = list((graph or {}).get("nodes") or [])
    edges = list((graph or {}).get("edges") or [])
    if not nodes:
        return (
            "画布上没有节点，无法生成。请从左侧「节点」添加「图生视频」等节点，"
            "或用模板预填后再一键跑。"
        )
    by_id = {str(n.get("id")): n for n in nodes if n.get("id") is not None}
    types = {nid: _normalize_type(n) for nid, n in by_id.items()}
    ids = list(by_id.keys())
    targets = [str(x) for x in (target_ids or []) if x]
    full_run = not targets
    if targets:
        if any(t not in by_id for t in targets):
            return "选中的节点已不在画布上，无法生成。"
    else:
        if not any(is_exit_type(types.get(nid) or "") for nid in ids):
            extras = [
                _label(nid, types, by_id)
                for nid in ids
                if node_spec(types.get(nid) or "").get("orphan") == "full_run_forbid"
            ]
            if extras:
                return (
                    "没有可出片的节点，无法一键跑。"
                    f"画布上的「{'、'.join(extras[:3])}」需要接到「图生视频」「文生图」「混音」或「字幕」，"
                    "或选中该节点单独点「生成」。"
                )
            return "没有可出片的节点。请添加「图生视频」「文生图」「混音」或「字幕」后再一键跑。"

    down, up = _adj(edges, set(ids))
    if _has_cycle(ids, down):
        return "节点图存在环或无效依赖，无法执行。"

    if full_run:
        islands = [
            comp
            for comp in _undirected_components(ids, edges)
            if any(is_producer_type(types.get(nid) or "") for nid in comp)
        ]
        if len(islands) > 1:
            names = []
            for comp in islands[:4]:
                pick = next(
                    (nid for nid in comp if is_exit_type(types.get(nid) or "")),
                    next((nid for nid in comp if is_producer_type(types.get(nid) or "")), comp[0]),
                )
                names.append(f"「{_label(pick, types, by_id)}」")
            extra = " 等" if len(islands) > 4 else ""
            return (
                f"画布上有 {len(islands)} 条互不相连的工作流（{'、'.join(names)}{extra}）。"
                "一键跑只能跑一条完整链路，请删掉多余节点或把它们连起来。"
            )
        exits = {nid for nid in ids if is_exit_type(types.get(nid) or "")}
        for nid in ids:
            if node_spec(types.get(nid) or "").get("orphan") != "full_run_forbid":
                continue
            if is_exit_type(types.get(nid) or ""):
                continue
            if not _can_reach(nid, exits, down):
                return (
                    f"「{_label(nid, types, by_id)}」没有连接到任何出片节点，工作流不完整。"
                    "请把它接到「图生视频」等节点，或删掉后再一键跑。"
                )

    if targets:
        check_ids = targets
    else:
        exits = [nid for nid in ids if is_exit_type(types.get(nid) or "")]
        relevant = set(exits)
        stack = list(exits)
        while stack:
            u = stack.pop()
            for p in up.get(u, []):
                if p not in relevant:
                    relevant.add(p)
                    stack.append(p)
        check_ids = [nid for nid in ids if nid in relevant]

    invalid_edge = _invalid_edge_reason(types, by_id, edges, check_ids)
    if invalid_edge:
        return invalid_edge

    for nid in check_ids:
        reason = _node_input_reason(nid, types, by_id, edges)
        if reason:
            return reason
    forbid = _edge_forbid_reason(types, by_id, edges, check_ids)
    if forbid:
        return forbid

    pool_ids = targets if targets else ids
    flags = {"video": has_video_model, "llm": has_llm_model, "tts": has_tts_model, "image": has_image_model}
    msgs = {
        "video": "暂无可用视频模型，无法图生视频。请超管启用渠道后再一键跑。",
        "llm": "暂无可用 LLM 渠道。请超管启用「本地 LLM 模拟」，或填写真模型 Key 后再一键跑。",
        "tts": "暂无可用 TTS 渠道。请确认 aisrv 已启动，且超管已启用 Edge TTS 渠道。",
        "image": "暂无可用文生图渠道。请超管启用「本地文生图模拟」后再一键跑。",
    }
    for nid in pool_ids:
        ch = needs_channel(types.get(nid) or "")
        if ch and flags.get(ch) is False:
            return msgs.get(ch) or f"暂无可用 {ch} 渠道。"
    return None
