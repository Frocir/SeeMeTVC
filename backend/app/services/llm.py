"""OpenAI-compatible + Anthropic chat for canvas LLM nodes."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.models import Channel
from app.services.net import make_async_client

LLM_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=5.0)

LLM_ROLES = ("chat", "brief", "shot")

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


def is_simulate_channel(channel: Channel) -> bool:
    provider = (channel.provider or "").strip().lower()
    model = (channel.model_id or "").strip().lower()
    kind = (channel.kind or "").strip().lower()
    if kind and kind != "llm":
        return False
    return provider in {"mock", "local-simulate", "simulate"} or model == "llm-local-simulate"


def simulate_complete(*, role: str, user: str, want_narration: bool = True) -> str:
    """Instant local reply so demo runs without a real LLM key."""
    brand = "SeeMe"
    for line in (user or "").splitlines():
        if line.startswith("品牌："):
            brand = line.split("：", 1)[-1].strip() or brand
            break
    if role == "brief":
        return (
            f"{brand} 新品短片 Brief：柔光特写，先见产品再见面部气色，"
            "卖点落在水光肌与持妆，收束口号自然出画。"
        )
    if role == "shot":
        prompt = (
            '{"prompt":"Cinematic beauty close-up, soft key light, '
            f'{brand} device on vanity, dewy skin, slow push-in, 16:9"'
        )
        if want_narration:
            return prompt + ',"narration":"看见更好的自己，妆感干净，气色刚刚好。"}'
        return prompt + "}"
    return f"{brand} 美妆短片：柔光、产品特写、一句干净口播。"


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
    if is_simulate_channel(channel):
        return simulate_complete(
            role=role if role in LLM_ROLES else "chat",
            user=user,
            want_narration=want_narration,
        )
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
    if is_simulate_channel(channel):
        last = next((m["content"] for m in reversed(cleaned) if m["role"] == "user"), "")
        return simulate_complete(role="chat", user=last)
    key = (channel.api_key or "").strip()
    if not key:
        raise LlmError("未配置 LLM API Key，请超管填写并启用渠道，或改用「本地 LLM 模拟」")
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
    if is_simulate_channel(channel):
        result = _simulate_tools(messages, tools or [])
        if result.get("kind") == "tool_calls":
            yield result
            return
        text = str(result.get("text") or "")
        if text:
            yield {"kind": "token", "text": text}
        yield {"kind": "message", "text": text}
        return
    key = (channel.api_key or "").strip()
    if not key:
        raise LlmError("未配置 LLM API Key，请超管填写并启用渠道，或改用「本地 LLM 模拟」")
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


def _simulate_tools(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    names = {
        str((t.get("function") or {}).get("name") or t.get("name") or "")
        for t in tools
        if isinstance(t, dict)
    }
    last_user = ""
    last_role = ""
    for m in messages:
        last_role = str(m.get("role") or "")
        if last_role == "user":
            last_user = str(m.get("content") or "")
    if last_role == "tool":
        return {
            "kind": "message",
            "text": "已在画布上执行刚才的操作。还可以继续改节点、连线，或说明下一镜。",
        }
    text = last_user
    def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "tool_calls",
            "calls": [{"id": "sim_" + name, "name": name, "arguments": args}],
        }

    if "get_graph" in names and any(k in text for k in ("画布", "现在", "节点", "看看", "图上")):
        return _call("get_graph", {})
    if "add_node" in names:
        if any(k in text for k in ("文生图", "生图", "出图")):
            return _call("add_node", {"node_type": "TextToImage", "label": "文生图"})
        if any(k in text for k in ("图生视频", "出视频", "出片", "视频节点")):
            return _call("add_node", {"node_type": "ImageToVideo", "label": "图生视频"})
        if any(k in text for k in ("LLM", "单镜", "brief", "Brief", "文案节点")):
            role = "brief" if "brief" in text.lower() or "文案" in text else "shot"
            return _call(
                "add_node",
                {"node_type": "LlmText", "label": "LLM", "data": {"llmRole": role}},
            )
        if any(k in text for k in ("加节点", "加一个", "添加文本", "Brief 节点", "文本节点", "搭")):
            return _call("add_node", {"node_type": "TextAsset", "label": "Brief"})
    return {
        "kind": "message",
        "text": (
            "（本地模拟）我可以帮你问清 Brief，或在画布上加节点/连线。"
            "试着说：加一个 Brief 文本节点、加 LLM 单镜、或说明品牌和卖点。"
        ),
    }


def _openai_payload_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system.strip():
        out.append({"role": "system", "content": system.strip()})
    for m in messages:
        role = str(m.get("role") or "")
        if role not in {"user", "assistant", "tool"}:
            continue
        item: dict[str, Any] = {"role": role}
        if role == "tool":
            item["content"] = str(m.get("content") or "")
            tcid = str(m.get("tool_call_id") or "")
            if tcid:
                item["tool_call_id"] = tcid
        elif role == "assistant" and m.get("tool_calls"):
            item["content"] = m.get("content")
            item["tool_calls"] = m["tool_calls"]
        else:
            item["content"] = str(m.get("content") or "")
        out.append(item)
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
    payload: dict[str, Any] = {
        "model": model,
        "messages": _openai_payload_messages(system, messages),
        "temperature": 0.7,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    acc_text: list[str] = []
    acc_tools: dict[int, dict[str, str]] = {}
    try:
        async with make_async_client(timeout=AGENT_LLM_TIMEOUT) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="replace")[:300]
                    raise LlmError(f"LLM 上游 HTTP {resp.status_code}：{body}")
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
                        yield {"kind": "token", "text": piece}
                    for tc in delta.get("tool_calls") or []:
                        if not isinstance(tc, dict):
                            continue
                        idx = int(tc.get("index") or 0)
                        slot = acc_tools.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = str(tc["id"])
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = str(fn["name"])
                        if fn.get("arguments"):
                            slot["arguments"] += str(fn["arguments"])
    except LlmError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LlmError(f"LLM 请求失败：{exc}") from exc
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
    anth_msgs: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role") or "")
        if role == "tool":
            anth_msgs.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(m.get("tool_call_id") or ""),
                            "content": str(m.get("content") or ""),
                        }
                    ],
                }
            )
        elif role in {"user", "assistant"}:
            if m.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": str(m["content"])})
                for tc in m["tool_calls"]:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": fn.get("name") or tc.get("name"),
                            "input": args if isinstance(args, dict) else {},
                        }
                    )
                anth_msgs.append({"role": "assistant", "content": blocks})
            else:
                anth_msgs.append({"role": role, "content": str(m.get("content") or "")})
    payload: dict[str, Any] = {"model": model, "max_tokens": 4096, "messages": anth_msgs or [{"role": "user", "content": "你好"}]}
    if system.strip():
        payload["system"] = system.strip()
    if tools:
        payload["tools"] = _anthropic_tools(tools)
    headers = anthropic_headers(key, base_url=channel.base_url)
    try:
        async with make_async_client(timeout=AGENT_LLM_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001
        raise LlmError(f"LLM 请求失败：{exc}") from exc
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
        elif b.get("type") == "tool_use":
            calls.append(
                {
                    "id": str(b.get("id") or ""),
                    "name": str(b.get("name") or ""),
                    "arguments": b.get("input") if isinstance(b.get("input"), dict) else {},
                }
            )
    if calls:
        yield {"kind": "tool_calls", "calls": calls}
        return
    text = "\n".join(t for t in texts if t.strip()).strip()
    if text:
        yield {"kind": "token", "text": text}
    yield {"kind": "message", "text": text}
