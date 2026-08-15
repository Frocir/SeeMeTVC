"""Unified model capability matrix for canvas params and run-time checks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models import Channel
from app.services import seedance

IMAGE_SIZES_OPENAI = ["1024x1024", "1024x1792", "1792x1024"]
IMAGE_SIZES_GEMINI = ["1:1", "16:9", "9:16", "1024x1024", "1024x1792", "1792x1024"]
VIDEO_ASPECTS = ["16:9", "9:16", "1:1"]


class CapabilityError(Exception):
    pass


@dataclass
class ModelCapabilities:
    kind: str = "video"
    vision: bool | None = None
    supports_text_to_image: bool | None = None
    supports_image_to_image: bool | None = None
    supports_multi_reference: bool | None = None
    supports_negative_prompt: bool | None = None
    supports_seed: bool | None = None
    supports_batch: bool | None = None
    supports_image_strength: bool | None = None
    supports_text_to_video: bool | None = None
    supports_image_to_video: bool | None = None
    supports_first_last_frame: bool | None = None
    supports_style_reference: bool | None = None
    supports_character_reference: bool | None = None
    supports_product_reference: bool | None = None
    supports_transcription: bool | None = None
    sizes: list[str] | None = None
    aspects: list[str] | None = None
    duration_min: int | None = None
    duration_max: int | None = None
    provider_params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if value is None:
                continue
            if key == "provider_params" and not value:
                continue
            out[key] = value
        return out

    def flag(self, name: str) -> bool:
        val = getattr(self, name, None)
        return bool(val)


def parse_config_json(raw: str | dict | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def dump_config_json(data: dict[str, Any] | None) -> str:
    return json.dumps(data or {}, ensure_ascii=False)


def _overlay_caps(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if value is None:
            continue
        if key == "provider_params" and isinstance(value, dict):
            merged[key] = {**(merged.get(key) or {}), **value}
            continue
        merged[key] = value
    return merged


def _from_dict(data: dict[str, Any]) -> ModelCapabilities:
    known = {f.name for f in ModelCapabilities.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key in known:
            kwargs[key] = value
        else:
            params = kwargs.setdefault("provider_params", {})
            if isinstance(params, dict):
                params[key] = value
    kind = str(kwargs.get("kind") or "video")
    kwargs["kind"] = kind
    return ModelCapabilities(**kwargs)


def provider_default_capabilities(channel: Channel) -> dict[str, Any]:
    kind = (channel.kind or "video").strip().lower() or "video"
    provider = (channel.provider or "").strip().lower()
    model = (channel.model_id or "").strip().lower()

    if kind == "image":
        from app.services import image_gen

        gemini = image_gen.is_gemini_image_channel(channel)
        return {
            "kind": "image",
            "supports_text_to_image": True,
            "supports_image_to_image": True,
            "supports_multi_reference": False,
            "supports_negative_prompt": True if gemini else False,
            "supports_seed": False,
            "supports_batch": False,
            "supports_image_strength": False,
            "sizes": list(IMAGE_SIZES_GEMINI if gemini else IMAGE_SIZES_OPENAI),
        }

    if kind == "video":
        family = seedance.fal_family(channel)
        if provider in {"agnes", "pavo", "agnes-pavo"}:
            return {
                "kind": "video",
                "supports_image_to_video": True,
                "supports_text_to_video": True,
                "supports_first_last_frame": False,
                "supports_style_reference": False,
                "supports_character_reference": False,
                "supports_product_reference": False,
                "duration_min": 2,
                "duration_max": 18,
                "aspects": list(VIDEO_ASPECTS),
            }
        if family == "seedance-2.5" or "2.5" in model or "seedance-2" in model:
            return {
                "kind": "video",
                "supports_image_to_video": True,
                "supports_text_to_video": True,
                "supports_first_last_frame": True,
                "supports_style_reference": False,
                "supports_character_reference": False,
                "supports_product_reference": False,
                "duration_min": 4,
                "duration_max": 30,
                "aspects": list(VIDEO_ASPECTS),
            }
        if family == "seedance-lite" or "lite" in model:
            return {
                "kind": "video",
                "supports_image_to_video": True,
                "supports_text_to_video": True,
                "supports_first_last_frame": False,
                "supports_style_reference": False,
                "supports_character_reference": False,
                "supports_product_reference": False,
                "duration_min": 2,
                "duration_max": 12,
                "aspects": list(VIDEO_ASPECTS),
            }
        return {
            "kind": "video",
            "supports_image_to_video": True,
            "supports_text_to_video": True,
            "supports_first_last_frame": False,
            "supports_style_reference": False,
            "supports_character_reference": False,
            "supports_product_reference": False,
            "duration_min": 2,
            "duration_max": 30,
            "aspects": list(VIDEO_ASPECTS),
        }

    if kind == "llm":
        return {"kind": "llm", "vision": True}

    if kind == "tts":
        return {"kind": "tts"}

    if kind == "asr":
        return {"kind": "asr", "supports_transcription": True}

    return {"kind": kind}


def get_channel_capabilities(channel: Channel) -> ModelCapabilities:
    base = provider_default_capabilities(channel)
    overlay = parse_config_json(channel.config_json).get("capabilities")
    if isinstance(overlay, dict) and overlay:
        base = _overlay_caps(base, overlay)
    base["kind"] = (channel.kind or base.get("kind") or "video").strip().lower() or "video"
    return _from_dict(base)


def _filled(data: dict[str, Any], key: str) -> bool:
    val = data.get(key)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, (int, float)):
        return True
    return bool(val)


def validate_node_params_against_capabilities(
    node_type: str,
    data: dict[str, Any],
    caps: ModelCapabilities,
) -> str | None:
    """Return a user-facing error if the node asks for unsupported inputs."""
    nt = (node_type or "").strip()
    if nt in {"ImageToVideo", "ShotGenerate"}:
        first = str(data.get("first_image_url") or data.get("image_url") or "").strip()
        last = str(data.get("last_image_url") or "").strip()
        if last and not caps.flag("supports_first_last_frame"):
            return "当前模型不支持首尾帧输入，请更换模型或移除尾帧。"
        if last and not first:
            return "已填写尾帧，请同时提供首帧 / 参考图。"
        if _filled(data, "style_image_url") and not caps.flag("supports_style_reference"):
            return "当前模型不支持风格参考图，请更换模型或移除风格图。"
        if _filled(data, "character_image_url") and not caps.flag("supports_character_reference"):
            return "当前模型不支持角色参考图，请更换模型或移除角色图。"
        if _filled(data, "product_image_url") and not caps.flag("supports_product_reference"):
            return "当前模型不支持产品参考图，请更换模型或移除产品图。"
        if first and not caps.flag("supports_image_to_video"):
            return "当前模型不支持图生视频，请移除参考图或更换模型。"
        if not first and not caps.flag("supports_text_to_video"):
            return "当前模型不支持文生视频，请接参考图或更换模型。"
        return None

    if nt == "TextToImage":
        if _filled(data, "image_url") and not caps.flag("supports_image_to_image"):
            return "当前模型不支持图生图，请移除参考图或更换模型。"
        return None

    return None


def filter_image_params(data: dict[str, Any], caps: ModelCapabilities) -> dict[str, Any]:
    """Keep only T2I params the channel advertises. Unsupported values are dropped, not errors."""
    out: dict[str, Any] = {}
    sizes = [str(s) for s in (caps.sizes or []) if str(s).strip()]
    size = str(data.get("size") or "").strip()
    if sizes:
        out["size"] = size if size in sizes else sizes[0]
    if caps.flag("supports_negative_prompt"):
        neg = str(data.get("negative_prompt") or "").strip()
        if neg:
            out["negative_prompt"] = neg
    if caps.flag("supports_seed"):
        try:
            seed = int(data.get("seed"))
            if seed >= 0:
                out["seed"] = seed
        except (TypeError, ValueError):
            pass
    if caps.flag("supports_batch"):
        try:
            n = int(data.get("batch_size") or 1)
            out["batch_size"] = max(1, min(n, 4))
        except (TypeError, ValueError):
            out["batch_size"] = 1
    if caps.flag("supports_image_strength"):
        try:
            strength = float(data.get("image_strength"))
            out["image_strength"] = max(0.0, min(strength, 1.0))
        except (TypeError, ValueError):
            pass
    return out
