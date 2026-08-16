"""OpenAI-compatible + Anthropic chat for canvas LLM nodes."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm_ids import is_official_deepseek_url
from app.models import Channel
from app.services.net import describe_upstream_disconnect, is_transient_httpx, make_async_client

LLM_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=5.0)

SYSTEM_BRIEF = (
    "你是美妆 TVC 文案。根据用户给出的品牌、卖点、口号，写一段可直接给下游使用的 Brief。"
    "只输出正文，不要标题或 Markdown。"
)

SYSTEM_SHOT = (
    "你是美妆广告单镜写手。根据 Brief 只写一镜。输出严格 JSON（不要 Markdown 围栏）："
    '{"prompt":"该镜的画面提示词","narration":"一句适合口播的中文旁白，约 15–40 字"}。'
    "禁止 scenes 数组，禁止多镜。"
)

SYSTEM_SHOT_SILENT = (
    "你是美妆广告单镜写手。根据 Brief 只写一镜。输出严格 JSON（不要 Markdown 围栏）："
    '{"prompt":"该镜的画面提示词"}。'
    "不要 narration，禁止 scenes 数组，禁止多镜。"
)


class LlmError(Exception):
    pass


def default_system(role: str, want_narration: bool = True) -> str:
    if role == "shot":
        return SYSTEM_SHOT if want_narration else SYSTEM_SHOT_SILENT
    return {
        "brief": SYSTEM_BRIEF,
        "chat": "",
    }.get(role, "")


def _openai_root(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return "https://api.openai.com/v1"
    if root.endswith("/v1"):
        return root
    return f"{root}/v1"


def _anthropic_root(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    if not root:
        return "https://api.anthropic.com"
    for suffix in ("/v1/messages", "/v1"):
        if root.lower().endswith(suffix):
            root = root[: -len(suffix)].rstrip("/")
            break
    return root or "https://api.anthropic.com"


def _is_official_anthropic(base_url: str) -> bool:
    host = (base_url or "").lower()
    return "api.anthropic.com" in host


def anthropic_headers(key: str, *, base_url: str) -> dict[str, str]:
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    # Custom gateways often accept Bearer as well as x-api-key.
    if not _is_official_anthropic(base_url):
        headers["Authorization"] = f"Bearer {key}"
    return headers


async def chat_complete(
    channel: Channel,
    *,
    system: str,
    user: str,
    role: str = "chat",
    want_narration: bool = True,
) -> str:
    user = (user or "").strip()
    if not user:
        raise LlmError("LLM 缺少输入文本")
    return await chat_messages(
        channel,
        messages=[{"role": "user", "content": user}],
        system=system,
    )


def _normalize_chat_messages(raw: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] = f"{out[-1]['content']}\n{content}"
        else:
            out.append({"role": role, "content": content})
    if out and out[0]["role"] != "user":
        out = out[1:]
    return out


async def chat_messages(
    channel: Channel,
    *,
    messages: list[dict[str, str]],
    system: str = "",
) -> str:
    cleaned = _normalize_chat_messages(messages)
    if not cleaned:
        raise LlmError("请输入内容")
    key = (channel.api_key or "").strip()
    if not key:
        raise LlmError("未配置 LLM API Key，请超管填写并启用渠道")
    model = (channel.upstream_model or channel.model_id or "").strip()
    if not model:
        raise LlmError("LLM 渠道未填写 upstream_model")
    provider = (channel.provider or "openai").lower()
    if provider == "anthropic":
        return await _anthropic(channel, key=key, model=model, system=system, messages=cleaned)
    return await _openai(channel, key=key, model=model, system=system, messages=cleaned)


async def _openai(
    channel: Channel,
    *,
    key: str,
    model: str,
    system: str,
    user: str = "",
    messages: list[dict[str, str]] | None = None,
) -> str:
    url = f"{_openai_root(channel.base_url)}/chat/completions"
    payload_messages: list[dict[str, str]] = []
    if system.strip():
        payload_messages.append({"role": "system", "content": system.strip()})
    if messages:
        payload_messages.extend(messages)
    else:
        payload_messages.append({"role": "user", "content": user})
    payload = {"model": model, "messages": payload_messages, "temperature": 0.7}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with make_async_client(timeout=LLM_HTTP_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        raise LlmError(f"LLM 请求失败（约 20 秒未响应即超时）：{exc}") from exc
    if resp.status_code >= 400:
        raise LlmError(f"LLM 上游 HTTP {resp.status_code}：{(resp.text or '')[:300]}")
    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError("LLM 返回无法解析") from exc
    if not isinstance(text, str) or not text.strip():
        raise LlmError("LLM 返回空内容")
    return text.strip()


async def _anthropic(
    channel: Channel,
    *,
    key: str,
    model: str,
    system: str,
    user: str = "",
    messages: list[dict[str, str]] | None = None,
) -> str:
    url = f"{_anthropic_root(channel.base_url)}/v1/messages"
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "messages": messages or [{"role": "user", "content": user}],
    }
    if system.strip():
        payload["system"] = system.strip()
    headers = anthropic_headers(key, base_url=channel.base_url)
    try:
        async with make_async_client(timeout=LLM_HTTP_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        raise LlmError(f"LLM 请求失败（约 20 秒未响应即超时）：{exc}") from exc
    if resp.status_code >= 400:
        raise LlmError(f"LLM 上游 HTTP {resp.status_code}：{(resp.text or '')[:300]}")
    data = resp.json()
    blocks = data.get("content") or []
    parts = [b.get("text") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    text = "\n".join(p for p in parts if isinstance(p, str) and p.strip())
    if not text.strip():
        raise LlmError("LLM 返回空内容")
    return text.strip()


def parse_shot(raw: str, want_narration: bool = True) -> dict[str, Any]:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LlmError("单镜输出不是 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LlmError(f"单镜 JSON 解析失败：{exc}") from exc
    if isinstance(data.get("scenes"), list):
        raise LlmError("单镜禁止 scenes[]，请只输出一条 prompt")
    prompt = str(data.get("prompt") or "").strip()
    narration = str(data.get("narration") or "").strip()
    if not prompt:
        raise LlmError("单镜 JSON 缺少 prompt")
    if want_narration and not narration:
        raise LlmError("单镜 JSON 缺少 narration 旁白")
    if not want_narration:
        narration = ""
    return {"prompt": prompt, "narration": narration, "text": prompt}


AGENT_LLM_TIMEOUT = httpx.Timeout(90.0, connect=8.0)


async def chat_turn(
    channel: Channel,
    *,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """One Agent LLM step. Yields token / message / tool_calls dicts."""
    key = (channel.api_key or "").strip()
    if not key:
        raise LlmError("未配置 LLM API Key，请超管填写并启用渠道")
    model = (channel.upstream_model or channel.model_id or "").strip()
    if not model:
        raise LlmError("LLM 渠道未填写 upstream_model")
    provider = (channel.provider or "openai").lower()
    if provider == "anthropic":
        async for ev in _anthropic_turn(
            channel, key=key, model=model, system=system, messages=messages, tools=tools or []
        ):
            yield ev
        return
    async for ev in _openai_turn(
        channel, key=key, model=model, system=system, messages=messages, tools=tools or []
    ):
        yield ev


def _openai_payload_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI/DeepSeek: never send unpaired tool_calls. History is text; current loop keeps tools."""
    return _pack_openai_agent_messages(system, messages)


def _is_tool_pairing_error(body: str) -> bool:
    low = (body or "").lower()
    return "tool_call" in low and (
        "insufficient" in low or "must be followed" in low or "tool_call_id" in low
    )


def _pack_openai_text_fallback(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Last user text only. Canvas lives in system — enough to call tools again."""
    last = "请继续"
    for m in messages:
        if str(m.get("role") or "") == "user":
            text = str(m.get("content") or "").strip()
            if text:
                last = text
    out: list[dict[str, Any]] = []
    if system.strip():
        out.append({"role": "system", "content": system.strip()})
    out.append({"role": "user", "content": last})
    return out


async def _openai_turn(
    channel: Channel,
    *,
    key: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    url = f"{_openai_root(channel.base_url)}/chat/completions"
    packed = _pack_openai_agent_messages(system, messages)
    pairing_retried = False
    payload: dict[str, Any] = {
        "model": model,
        "messages": packed,
        "temperature": 0.7,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if is_official_deepseek_url(channel.base_url):
        # V4 Pro 默认 thinking，Agent 需要直接出话 / 调工具。
        payload["thinking"] = {"type": "disabled"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    acc_text: list[str] = []
    acc_tools: dict[int, dict[str, str]] = {}
    last_exc: Exception | None = None
    for attempt in range(3):
        acc_text = []
        acc_tools = {}
        yielded = False
        try:
            async with make_async_client(timeout=AGENT_LLM_TIMEOUT) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")[:300]
                        if not pairing_retried and _is_tool_pairing_error(body):
                            pairing_retried = True
                            payload["messages"] = _pack_openai_text_fallback(system, messages)
                            continue
                        raise LlmError(f"对话模型上游 HTTP {resp.status_code}：{body}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choice = (chunk.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        piece = delta.get("content")
                        if isinstance(piece, str) and piece:
                            acc_text.append(piece)
                            yielded = True
                            yield {"kind": "token", "text": piece}
                        for tc in delta.get("tool_calls") or []:
                            if not isinstance(tc, dict):
                                continue
                            yielded = True
                            idx = int(tc.get("index") or 0)
                            slot = acc_tools.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                slot["id"] = str(tc["id"])
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = str(fn["name"])
                            if fn.get("arguments"):
                                slot["arguments"] += str(fn["arguments"])
            break
        except LlmError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if yielded or not is_transient_httpx(exc) or attempt >= 2:
                raise LlmError(
                    describe_upstream_disconnect(exc, who="对话模型（Agent 用的 LLM，不是生视频 Key）")
                ) from exc
            await asyncio.sleep(0.8)
    else:
        raise LlmError(
            describe_upstream_disconnect(
                last_exc or RuntimeError("unknown"),
                who="对话模型（Agent 用的 LLM，不是生视频 Key）",
            )
        )
    if acc_tools:
        calls = []
        for idx in sorted(acc_tools):
            slot = acc_tools[idx]
            raw = slot["arguments"] or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            calls.append(
                {
                    "id": slot["id"] or f"call_{idx}",
                    "name": slot["name"],
                    "arguments": args,
                }
            )
        yield {"kind": "tool_calls", "calls": calls}
        return
    yield {"kind": "message", "text": "".join(acc_text).strip()}


_TOOL_STUB = json.dumps(
    {"error": "这次工具没有回传结果（上次出片或确认中断了）。请再调用一次。"},
    ensure_ascii=False,
)


def _tool_call_id(tc: dict[str, Any], fallback: str = "") -> str:
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    return str(
        tc.get("id")
        or tc.get("tool_use_id")
        or tc.get("toolUseId")
        or fn.get("name")
        or tc.get("name")
        or fallback
        or ""
    ).strip()


def _tool_name(tc: dict[str, Any]) -> str:
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    return str(fn.get("name") or tc.get("name") or "").strip()


def _tool_input(tc: dict[str, Any]) -> dict[str, Any]:
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    args = fn.get("arguments") if fn else tc.get("arguments") or tc.get("input")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return args if isinstance(args, dict) else {}


def align_messages_for_tools(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put every tool_result immediately after its assistant tool_use. Keep user text after that."""
    out: list[dict[str, Any]] = []
    i = 0
    n = len(messages)
    while i < n:
        m = messages[i]
        role = str(m.get("role") or "")
        if role == "tool":
            i += 1
            continue
        raw_calls = m.get("tool_calls") if role == "assistant" else None
        calls = [dict(tc) for tc in (raw_calls or []) if isinstance(tc, dict)]
        if role == "assistant" and calls:
            ids: list[str] = []
            for k, tc in enumerate(calls):
                tid = _tool_call_id(tc, fallback=f"toolu_local_{i}_{k}")
                tc["id"] = tid
                ids.append(tid)
            got: dict[str, dict[str, Any]] = {}
            intervening: list[dict[str, Any]] = []
            j = i + 1
            while j < n:
                nxt = messages[j]
                nr = str(nxt.get("role") or "")
                if nr == "assistant" and nxt.get("tool_calls"):
                    break
                if nr == "tool":
                    tid = str(nxt.get("tool_call_id") or "")
                    if tid:
                        got[tid] = nxt
                elif nr in {"user", "assistant"} and str(nxt.get("content") or "").strip():
                    intervening.append(nxt)
                j += 1
            out.append({"role": "assistant", "content": None, "tool_calls": calls})
            for tid in ids:
                if tid in got:
                    row = dict(got[tid])
                    row["tool_call_id"] = tid
                    out.append(row)
                else:
                    out.append({"role": "tool", "tool_call_id": tid, "content": _TOOL_STUB})
            out.extend(intervening)
            i = j
            continue
        if role in {"user", "assistant"} and str(m.get("content") or "").strip():
            out.append(m)
        i += 1
    return out


def _normalize_openai_tool_calls(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, tc in enumerate(raw or []):
        if not isinstance(tc, dict):
            continue
        tid = _tool_call_id(tc, fallback=f"call_{i}")
        if not tid:
            continue
        out.append(
            {
                "id": tid,
                "type": "function",
                "function": {
                    "name": _tool_name(tc) or "unknown",
                    "arguments": json.dumps(_tool_input(tc), ensure_ascii=False),
                },
            }
        )
    return out


def _in_progress_tool_suffix(aligned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep trailing assistant tool_calls + results (the live tool round). Else drop tools."""
    i = len(aligned) - 1
    tools: list[dict[str, Any]] = []
    while i >= 0 and str(aligned[i].get("role") or "") == "tool":
        tools.append(aligned[i])
        i -= 1
    tools.reverse()
    if i < 0:
        return []
    head = aligned[i]
    if str(head.get("role") or "") != "assistant" or not head.get("tool_calls"):
        return []
    calls = _normalize_openai_tool_calls(list(head.get("tool_calls") or []))
    if not calls:
        return []
    by_id = {str(t.get("tool_call_id") or ""): t for t in tools if t.get("tool_call_id")}
    packed = [
        {
            "role": "tool",
            "tool_call_id": c["id"],
            "content": str((by_id.get(c["id"]) or {}).get("content") or _TOOL_STUB),
        }
        for c in calls
    ]
    return [{"role": "assistant", "content": "", "tool_calls": calls}, *packed]


def _merge_text_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role") or "")
        if role == "tool" or (role == "assistant" and m.get("tool_calls")):
            continue
        text = str(m.get("content") or "").strip()
        if role not in {"user", "assistant"} or not text:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] = f"{out[-1]['content']}\n{text}"
        else:
            out.append({"role": role, "content": text})
    return out


def _openai_pairing_ok(packed: list[dict[str, Any]]) -> bool:
    for i, m in enumerate(packed):
        if str(m.get("role") or "") != "assistant" or not m.get("tool_calls"):
            continue
        calls = [tc for tc in (m.get("tool_calls") or []) if isinstance(tc, dict)]
        ids = [str(tc.get("id") or "") for tc in calls]
        if not ids or any(not tid for tid in ids):
            return False
        for j, tid in enumerate(ids):
            nxt = packed[i + 1 + j] if i + 1 + j < len(packed) else None
            if not nxt or str(nxt.get("role") or "") != "tool" or str(nxt.get("tool_call_id") or "") != tid:
                return False
    return True


def _last_spoken_role(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        role = str(m.get("role") or "")
        if role == "user" and str(m.get("content") or "").strip():
            return "user"
        if role == "tool":
            return "tool"
        if role == "assistant" and (m.get("tool_calls") or str(m.get("content") or "").strip()):
            return "assistant"
    return ""


def _pack_openai_agent_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aligned = align_messages_for_tools(messages)
    # A new user line means the previous tool round is over. Never replay those tool_calls.
    suffix = [] if _last_spoken_role(messages) == "user" else _in_progress_tool_suffix(aligned)
    prefix = aligned[: len(aligned) - len(suffix)] if suffix else aligned
    text = _merge_text_turns(prefix)
    while text and text[0]["role"] != "user":
        text = text[1:]
    if not text:
        text = [{"role": "user", "content": "请继续"}]
    out: list[dict[str, Any]] = []
    if system.strip():
        out.append({"role": "system", "content": system.strip()})
    out.extend(text)
    out.extend(suffix)
    if not _openai_pairing_ok(out):
        return _pack_openai_text_fallback(system, messages)
    return out


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bedrock 网关会把历史 tool_use 配对搞崩。Agent 只发最近的纯文本，画布状态在 system 里。"""
    texts: list[str] = []
    for m in messages:
        if str(m.get("role") or "") != "user":
            continue
        text = str(m.get("content") or "").strip()
        if text:
            texts.append(text)
    last = texts[-1] if texts else "请继续"
    return [{"role": "user", "content": last}]


def _parse_anthropic_tool_use(block: dict[str, Any]) -> dict[str, Any] | None:
    inner = block.get("toolUse") if isinstance(block.get("toolUse"), dict) else block
    tid = str(inner.get("id") or inner.get("tool_use_id") or inner.get("toolUseId") or "").strip()
    name = str(inner.get("name") or "").strip()
    raw_in = inner.get("input") if inner.get("input") is not None else inner.get("arguments")
    args = raw_in if isinstance(raw_in, dict) else {}
    if not tid and not name:
        return None
    return {"id": tid or f"toolu_{name}", "name": name or "unknown", "arguments": args}


def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        fn = t.get("function") if isinstance(t, dict) else None
        if not isinstance(fn, dict):
            continue
        out.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


async def _anthropic_turn(
    channel: Channel,
    *,
    key: str,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    url = f"{_anthropic_root(channel.base_url)}/v1/messages"
    anth_msgs = _to_anthropic_messages(messages)
    payload: dict[str, Any] = {"model": model, "max_tokens": 4096, "messages": anth_msgs}
    if system.strip():
        payload["system"] = system.strip()
    if tools:
        payload["tools"] = _anthropic_tools(tools)
    headers = anthropic_headers(key, base_url=channel.base_url)
    try:
        async with make_async_client(timeout=AGENT_LLM_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        raise LlmError(
            describe_upstream_disconnect(exc, who="对话模型（Agent 用的 LLM，不是生视频 Key）")
        ) from exc
    if resp.status_code >= 400:
        raise LlmError(f"LLM 上游 HTTP {resp.status_code}：{(resp.text or '')[:300]}")
    data = resp.json()
    calls = []
    texts: list[str] = []
    for b in data.get("content") or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            texts.append(str(b.get("text") or ""))
        elif b.get("type") in {"tool_use", "toolUse"} or b.get("toolUse"):
            parsed = _parse_anthropic_tool_use(b)
            if parsed:
                calls.append(parsed)
    if calls:
        yield {"kind": "tool_calls", "calls": calls}
        return
    text = "\n".join(t for t in texts if t.strip()).strip()
    if text:
        yield {"kind": "token", "text": text}
    yield {"kind": "message", "text": text}
