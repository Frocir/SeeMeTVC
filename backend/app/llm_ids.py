"""Public LLM hosts and model IDs. Keys never live here — only in the channel table."""

from urllib.parse import urlparse

TQX_LLM_HOST = "llm.tqx.ai"
TQX_LLM_BASE = f"https://{TQX_LLM_HOST}"

DEEPSEEK_HOST = "api.deepseek.com"
DEEPSEEK_BASE = f"https://{DEEPSEEK_HOST}"
DEEPSEEK_UPSTREAM = "deepseek-v4-pro"
DEEPSEEK_V4_PRO_MODEL_ID = "DeepSeek-V4-Pro"
DEEPSEEK_TQX_MODEL_ID = "DeepSeek-V4-Pro-tqx"
DEEPSEEK_TQX_UPSTREAM = "dsk_4p"

CLAUDE_SONNET46_MODEL_ID = "claude-sonnet-4-6"
GPT54_MODEL_ID = "g5.4"

DEFAULT_AGENT_MODEL_ID = DEEPSEEK_V4_PRO_MODEL_ID


def llm_host(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower()


def is_tqx_llm_url(url: str) -> bool:
    return llm_host(url) == TQX_LLM_HOST


def is_official_deepseek_url(url: str) -> bool:
    host = llm_host(url)
    return host == DEEPSEEK_HOST or host.endswith(".deepseek.com")
