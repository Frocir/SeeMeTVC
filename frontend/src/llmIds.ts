/** Public LLM hosts and model IDs. Keys never live here — only in the admin channel table. */

export const TQX_LLM_HOST = "llm.tqx.ai";
export const TQX_LLM_BASE = `https://${TQX_LLM_HOST}`;

export const DEEPSEEK_HOST = "api.deepseek.com";
export const DEEPSEEK_BASE = `https://${DEEPSEEK_HOST}`;
export const DEEPSEEK_UPSTREAM = "deepseek-v4-pro";
export const DEFAULT_AGENT_MODEL_ID = "DeepSeek-V4-Pro";
export const DEEPSEEK_TQX_MODEL_ID = "DeepSeek-V4-Pro-tqx";
export const DEEPSEEK_TQX_UPSTREAM = "dsk_4p";

export const CLAUDE_SONNET46_MODEL_ID = "claude-sonnet-4-6";
export const GPT54_MODEL_ID = "g5.4";

export function llmHost(url: string): string {
  const raw = (url || "").trim();
  if (!raw) return "";
  try {
    return new URL(raw.includes("://") ? raw : `https://${raw}`).hostname.toLowerCase();
  } catch {
    return "";
  }
}

export function isTqxLlmUrl(url: string): boolean {
  return llmHost(url) === TQX_LLM_HOST;
}

export function isOfficialDeepseekUrl(url: string): boolean {
  const host = llmHost(url);
  return host === DEEPSEEK_HOST || host.endsWith(".deepseek.com");
}
