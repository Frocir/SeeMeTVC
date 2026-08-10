import { uploadImage } from "./api";

function isPrivateHostname(host: string): boolean {
  const h = host.toLowerCase();
  if (!h || h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "[::1]") return true;
  if (h.endsWith(".local")) return true;
  const m = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(h);
  if (!m) return false;
  const a = Number(m[1]);
  const b = Number(m[2]);
  if (a === 10) return true;
  if (a === 127) return true;
  if (a === 192 && b === 168) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  return false;
}

/** True when Agnes/fal cannot fetch this URL from the public internet. */
export function isLocalOrSameOriginImage(url: string): boolean {
  if (!url) return false;
  if (url.startsWith("data:")) return false;
  if (url.startsWith("/uploads/") || url.startsWith("/beauty/")) return true;
  try {
    const u = new URL(url, window.location.origin);
    if (u.pathname.startsWith("/uploads/") || u.pathname.startsWith("/beauty/")) return true;
    return isPrivateHostname(u.hostname);
  } catch {
    return true;
  }
}

/**
 * Ensure reference image can be consumed by remote providers:
 * same-origin / LAN /beauty assets are re-uploaded to /uploads/...
 * (backend then inlines them as data URIs for Agnes).
 */
export async function ensureUpstreamImageUrl(url: string | null | undefined): Promise<string | null> {
  if (!url) return null;
  if (url.startsWith("data:")) return url;
  if (url.startsWith("/uploads/")) return url;

  let absolute: URL;
  try {
    absolute = new URL(url, window.location.origin);
  } catch {
    return url;
  }

  // Already our uploaded asset (absolute form)
  if (absolute.pathname.startsWith("/uploads/")) {
    return absolute.pathname;
  }

  if (!isLocalOrSameOriginImage(url)) {
    return url;
  }

  const fetchUrl = absolute.pathname + absolute.search;
  const res = await fetch(fetchUrl);
  if (!res.ok) {
    throw new Error(`无法读取参考图（${res.status}），请重新上传或换一张`);
  }
  const blob = await res.blob();
  const name =
    absolute.pathname.split("/").pop() ||
    `reference.${(blob.type.split("/")[1] || "jpg").replace("jpeg", "jpg")}`;
  const file = new File([blob], name, { type: blob.type || "image/jpeg" });
  const uploaded = await uploadImage(file);
  return uploaded.url;
}
