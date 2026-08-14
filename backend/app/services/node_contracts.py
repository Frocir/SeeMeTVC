"""Load node_contracts.yaml — single source for Agent cards, preflight, and connect."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONTRACTS_PATH = Path(__file__).resolve().parents[1] / "node_contracts.yaml"

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


def normalize_type_name(raw: str | None) -> str:
    s = str(raw or "").strip()
    if s in {"wf", "media", ""}:
        return "TextAsset"
    return LEGACY_TO_FREE.get(s, s)


@lru_cache(maxsize=1)
def load_contracts() -> dict[str, Any]:
    raw = yaml.safe_load(CONTRACTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw.get("nodes"):
        raise RuntimeError(f"节点规约无效：{CONTRACTS_PATH}")
    return raw


def public_payload() -> dict[str, Any]:
    data = load_contracts()
    return {
        "kind_compat": data.get("kind_compat") or {},
        "forbid_edges": data.get("forbid_edges") or [],
        "connect_defaults": data.get("connect_defaults") or [],
        "no_default_target_handles": data.get("no_default_target_handles") or [],
        "recipes": data.get("recipes") or [],
        "nodes": data.get("nodes") or {},
    }


def node_spec(node_type: str) -> dict[str, Any]:
    nt = normalize_type_name(node_type)
    spec = (load_contracts().get("nodes") or {}).get(nt)
    return spec if isinstance(spec, dict) else {}


def is_exit_type(node_type: str) -> bool:
    return bool(node_spec(node_type).get("exit"))


def is_producer_type(node_type: str) -> bool:
    spec = node_spec(node_type)
    if not spec:
        return False
    if spec.get("orphan") == "full_run_forbid":
        return True
    if spec.get("exit") or spec.get("run_tool"):
        return True
    return str(spec.get("group") or "") in {"produce", "finish"}


def needs_channel(node_type: str) -> str | None:
    ch = node_spec(node_type).get("channel")
    return str(ch) if ch else None


def _filled(data: dict, keys: list[str] | None) -> bool:
    for k in keys or []:
        val = data.get(k)
        if isinstance(val, str) and val.strip():
            return True
    return False


def render_cards() -> str:
    data = load_contracts()
    nodes: dict[str, dict] = data.get("nodes") or {}
    groups = [("asset", "素材"), ("produce", "生产"), ("finish", "成片")]
    lines = ["节点规约（搭图必须遵守）："]
    by_group: dict[str, list[tuple[str, dict]]] = {g: [] for g, _ in groups}
    for nid, spec in nodes.items():
        by_group.setdefault(str(spec.get("group") or "produce"), []).append((nid, spec))
    for gid, title in groups:
        items = by_group.get(gid) or []
        if not items:
            continue
        lines.append(f"## {title}")
        for nid, spec in items:
            ins = spec.get("inputs") or []
            outs = spec.get("outputs") or []
            in_s = ",".join(str(p.get("id")) for p in ins) or "—"
            out_s = ",".join(str(p.get("id")) for p in outs) or "—"
            req = []
            for p in ins:
                mode = str(p.get("required") or "optional")
                if mode != "optional":
                    req.append(f"{p.get('id')}({mode})")
            run = spec.get("run_tool") or "无"
            lines.append(
                f"- {nid}（{spec.get('label') or nid}）：{spec.get('purpose') or ''}"
                f" 何时用：{spec.get('when') or '—'} 不用：{spec.get('when_not') or '—'}"
                f" 入[{in_s}] 出[{out_s}] 必填：{','.join(req) or '无'} run={run}"
            )
    lines.append("## 整链配方")
    for rec in data.get("recipes") or []:
        lines.append(
            f"- {rec.get('label') or rec.get('id')}：{rec.get('when') or ''} "
            f"链：{rec.get('chain') or ''} 必须：{rec.get('must') or ''}"
        )
    lines.append(
        "一键跑禁止悬空生产者、禁止多条互不相连的生产链。"
        "选中节点单独生成允许孤立 LLM/TTS，但必须有正文。"
        "connect 必须写明 handle；MixAudio 的 bgm/vo 没有默认口。"
    )
    return "\n".join(lines)


def tool_add_node_description() -> str:
    names = []
    for nid, spec in (load_contracts().get("nodes") or {}).items():
        req = [
            str(p.get("id"))
            for p in (spec.get("inputs") or [])
            if str(p.get("required") or "optional") != "optional"
        ]
        bit = nid if not req else f"{nid}(必填口:{','.join(req)})"
        names.append(bit)
    return (
        "在画布上新增一个节点。node_type 必须是："
        + "、".join(names)
        + "。先 get_graph。生产者（LLM/TTS/文生图等）一键跑前必须接到出片链上。"
    )


def tool_connect_description() -> str:
    return (
        "连接两个节点的端口。必须传 source_handle 与 target_handle。"
        "文本接到图生视频/文生图用 target_handle=prompt，不要接到 image。"
        "混音三口：video / bgm / vo，省略则失败。TTS 只能接 vo，禁止接 bgm。"
    )


def kinds_compatible(source_handle: str, target_handle: str) -> bool:
    if not source_handle or not target_handle:
        return True
    if source_handle == target_handle:
        return True
    compat = load_contracts().get("kind_compat") or {}
    return target_handle in (compat.get(source_handle) or [])


def _port_ids(spec: dict, which: str) -> list[str]:
    return [str(p.get("id")) for p in (spec.get(which) or []) if p.get("id")]


def _output_kind(spec: dict, handle: str) -> str:
    for p in spec.get("outputs") or []:
        if str(p.get("id")) == handle:
            return str(p.get("kind") or handle)
    return handle


def resolve_connect_handles(
    source_type: str,
    target_type: str,
    source_handle: str = "",
    target_handle: str = "",
) -> tuple[str, str]:
    src = node_spec(source_type)
    tgt = node_spec(target_type)
    sh = (source_handle or "").strip()
    th = (target_handle or "").strip()
    no_default = {str(x) for x in (load_contracts().get("no_default_target_handles") or [])}
    src_outs = _port_ids(src, "outputs") or ["text"]
    tgt_ins = _port_ids(tgt, "inputs")

    if not sh:
        sh = src_outs[0]
    src_kind = _output_kind(src, sh) or sh

    if not th:
        audio_like = src_kind in {"audio", "bgm", "vo"}
        if audio_like and any(h in no_default for h in tgt_ins):
            raise ValueError(
                f"连接到「{tgt.get('label') or target_type}」必须写明 target_handle"
                f"（{' / '.join(h for h in tgt_ins if h in no_default or h == 'video')}），不能省略。"
            )
        defaults = load_contracts().get("connect_defaults") or []
        picked = ""
        for rule in defaults:
            if str(rule.get("source_kind") or "") != src_kind:
                continue
            for cand in rule.get("prefer_target") or []:
                if cand in tgt_ins and cand not in no_default:
                    picked = str(cand)
                    break
            if picked:
                break
        if not picked:
            compatible = [
                h
                for h in tgt_ins
                if h not in no_default and kinds_compatible(sh, h)
            ]
            if len(compatible) == 1:
                picked = compatible[0]
        if not picked:
            raise ValueError(
                f"无法默认连接 {source_type}.{sh} → {target_type}，请写明 source_handle 与 target_handle。"
            )
        th = picked
    return sh, th


def _tts_fed(source_id: str, source_type: str, edges: list[dict], types: dict[str, str]) -> bool:
    if source_type == "TtsSpeak":
        return True
    if source_type != "AudioTrim":
        return False
    for e in edges:
        if str(e.get("target")) != source_id:
            continue
        if types.get(str(e.get("source"))) == "TtsSpeak":
            return True
    return False


def forbid_edge_reason(
    *,
    source_id: str,
    source_type: str,
    target_type: str,
    target_handle: str,
    edges: list[dict],
    types: dict[str, str],
) -> str | None:
    th = (target_handle or "").strip()
    for rule in load_contracts().get("forbid_edges") or []:
        if str(rule.get("target_type") or "") != normalize_type_name(target_type):
            continue
        want_h = str(rule.get("target_handle") or "")
        if want_h and want_h != th:
            continue
        st = normalize_type_name(source_type)
        if st != str(rule.get("source_type") or ""):
            continue
        fed = str(rule.get("source_fed_by") or "")
        if fed and not _tts_fed(source_id, st, edges, types):
            continue
        return str(rule.get("message") or "非法连线")
    return None


def validate_connect(
    *,
    source_id: str,
    source_type: str,
    target_type: str,
    source_handle: str,
    target_handle: str,
    edges: list[dict],
    types: dict[str, str],
) -> None:
    sh, th = source_handle, target_handle
    src = node_spec(source_type)
    tgt = node_spec(target_type)
    src_outs = _port_ids(src, "outputs")
    tgt_ins = _port_ids(tgt, "inputs")
    if src_outs and sh not in src_outs:
        raise ValueError(
            f"「{src.get('label') or source_type}」没有输出端口 {sh}。可用：{', '.join(src_outs)}。"
        )
    if tgt_ins and th not in tgt_ins:
        raise ValueError(
            f"「{tgt.get('label') or target_type}」没有输入端口 {th}。可用：{', '.join(tgt_ins)}。"
        )
    if sh and th and not kinds_compatible(sh, th):
        raise ValueError(f"端口不兼容：{source_type}.{sh} 不能接到 {target_type}.{th}。")
    msg = forbid_edge_reason(
        source_id=source_id,
        source_type=source_type,
        target_type=target_type,
        target_handle=th,
        edges=edges,
        types=types,
    )
    if msg:
        raise ValueError(msg)
