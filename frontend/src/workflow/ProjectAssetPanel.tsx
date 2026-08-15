import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  bulkDeleteAssetVersions,
  listAssetVersions,
  patchAssetVersion,
  sendAssetVersionToCanvas,
  uploadFile,
  type AssetVersion,
  type ProjectAsset,
  type Workflow,
} from "../api";
import { NODE_TYPE_LABEL } from "./labels";
import { type WfNodeType } from "./types";

type KindFilter = "all" | "image" | "video" | "audio" | "output";
type HistoryKind = "all" | "image" | "video" | "audio" | "text" | "prompt";
type PanelTab = "library" | "history";

const KIND_LABEL: Record<string, string> = {
  image: "图",
  video: "视频",
  audio: "音频",
  output: "成片",
  text: "文案",
  prompt: "画面描述",
};

const NODE_LABEL = NODE_TYPE_LABEL;

type HistoryGraph = { nodes?: unknown[]; edges?: unknown[] };

export default function ProjectAssetPanel({
  workflowId,
  reloadKey = 0,
  onPlace,
  onApplyGraph,
}: {
  workflowId: number;
  reloadKey?: number;
  onPlace: (kind: WfNodeType, url: string, label: string) => void;
  onApplyGraph?: (graph: HistoryGraph, nodeId?: string) => void;
}) {
  const [tab, setTab] = useState<PanelTab>("library");
  const [items, setItems] = useState<ProjectAsset[]>([]);
  const [history, setHistory] = useState<AssetVersion[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [projects, setProjects] = useState<Workflow[]>([]);
  const [filter, setFilter] = useState<KindFilter>("all");
  const [historyFilter, setHistoryFilter] = useState<HistoryKind>("all");
  const [favOnly, setFavOnly] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copyId, setCopyId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function reloadLibrary() {
    const [assets, wfs] = await Promise.all([
      api<ProjectAsset[]>(`/api/workflows/${workflowId}/assets`),
      api<Workflow[]>("/api/workflows"),
    ]);
    setItems(assets);
    setProjects(wfs.filter((w) => w.id !== workflowId));
  }

  async function reloadHistory() {
    const out = await listAssetVersions(workflowId, {
      kind: historyFilter === "all" ? undefined : historyFilter,
      favorite: favOnly || undefined,
      limit: 80,
    });
    setHistory(out.items);
    setHistoryTotal(out.total);
  }

  useEffect(() => {
    void reloadLibrary().catch((e) => setError(e instanceof Error ? e.message : "加载素材失败"));
  }, [workflowId, reloadKey]);

  useEffect(() => {
    if (tab !== "history") return;
    void reloadHistory().catch((e) => setError(e instanceof Error ? e.message : "加载历史失败"));
  }, [workflowId, reloadKey, tab, historyFilter, favOnly]);

  const list = useMemo(
    () => items.filter((a) => filter === "all" || a.kind === filter),
    [items, filter],
  );

  async function onUpload(file: File) {
    setBusy(true);
    setError("");
    try {
      const isAudio = /\.(mp3|wav|m4a|aac)$/i.test(file.name) || file.type.startsWith("audio/");
      const isVideo = /\.(mp4|webm|mov)$/i.test(file.name) || file.type.startsWith("video/");
      const path = isAudio ? "/api/uploads/audio" : isVideo ? "/api/uploads/videos" : "/api/uploads/images";
      const kind = isAudio ? "audio" : isVideo ? "video" : "image";
      const up = await uploadFile(path, file);
      await api(`/api/workflows/${workflowId}/assets`, {
        method: "POST",
        body: JSON.stringify({
          url: up.url,
          kind,
          filename: up.filename,
        }),
      });
      await reloadLibrary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function copyTo(assetId: number, targetId: number) {
    setBusy(true);
    setError("");
    try {
      await api(`/api/workflows/${workflowId}/assets/${assetId}/copy`, {
        method: "POST",
        body: JSON.stringify({ target_workflow_id: targetId }),
      });
      setCopyId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "复制失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggleFav(row: AssetVersion) {
    setBusy(true);
    setError("");
    try {
      const next = await patchAssetVersion(row.id, { favorite: !row.favorite });
      setHistory((rows) => rows.map((x) => (x.id === row.id ? { ...x, favorite: next.favorite } : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "收藏失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeHistory(row: AssetVersion) {
    setBusy(true);
    setError("");
    try {
      await bulkDeleteAssetVersions([row.id]);
      setHistory((rows) => rows.filter((x) => x.id !== row.id));
      setHistoryTotal((n) => Math.max(0, n - 1));
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function sendHistory(row: AssetVersion) {
    setBusy(true);
    setError("");
    try {
      const out = await sendAssetVersionToCanvas(row.id);
      onApplyGraph?.(out.graph, out.node_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "发送到画布失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cv-section">
      <p className="eyebrow">本项目素材</p>
      <div className="cv-asset-filters">
        <button type="button" className={tab === "library" ? "active" : ""} onClick={() => setTab("library")}>
          素材库
        </button>
        <button type="button" className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>
          生成历史
        </button>
      </div>

      {tab === "library" ? (
        <>
          <div className="cv-asset-filters">
            {(["all", "image", "video", "audio", "output"] as const).map((k) => (
              <button
                key={k}
                type="button"
                className={filter === k ? "active" : ""}
                onClick={() => setFilter(k)}
              >
                {k === "all" ? "全部" : KIND_LABEL[k]}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="cv-add"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
          >
            <strong>上传图 / 视频 / 音频</strong>
            <span>放进这个项目</span>
          </button>
          <input
            ref={fileRef}
            type="file"
            hidden
            accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime,audio/mpeg,audio/wav,audio/mp4,audio/aac,.mp3,.wav,.m4a,.aac"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void onUpload(f);
            }}
          />
          {error && <p className="error">{error}</p>}
          <div className="cv-asset-list">
            {list.length === 0 && <p className="muted">暂无素材</p>}
            {list.map((a) => (
              <div key={a.id} className="cv-asset-item">
                {/\.(mp4|webm|mov)(\?|$)/i.test(a.url) ? (
                  <video className="cv-asset-thumb" src={a.url} muted playsInline preload="metadata" />
                ) : /\.(mp3|wav|m4a|aac)(\?|$)/i.test(a.url) ? (
                  <audio className="cv-asset-thumb" src={a.url} controls preload="metadata" />
                ) : (
                  <img className="cv-asset-thumb" src={a.url} alt="" />
                )}
                <strong>{a.filename || KIND_LABEL[a.kind] || a.kind}</strong>
                <span>{KIND_LABEL[a.kind] || a.kind}</span>
                <div className="cv-asset-actions">
                  <button
                    type="button"
                    className="linkish"
                    onClick={() =>
                      onPlace(
                        a.kind === "image" ? "ImageAsset" : a.kind === "audio" ? "AudioAsset" : "VideoAsset",
                        a.url,
                        a.filename || "素材",
                      )
                    }
                  >
                    放到画布
                  </button>
                  {projects.length > 0 && (
                    <button type="button" className="linkish" onClick={() => setCopyId(copyId === a.id ? null : a.id)}>
                      复制到…
                    </button>
                  )}
                </div>
                {copyId === a.id && (
                  <select
                    disabled={busy}
                    defaultValue=""
                    onChange={(e) => {
                      const id = Number(e.target.value);
                      if (id) void copyTo(a.id, id);
                    }}
                  >
                    <option value="">选择项目</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="cv-asset-filters">
            {(["all", "image", "video", "audio", "prompt", "text"] as const).map((k) => (
              <button
                key={k}
                type="button"
                className={historyFilter === k ? "active" : ""}
                onClick={() => setHistoryFilter(k)}
              >
                {k === "all" ? "全部" : KIND_LABEL[k]}
              </button>
            ))}
            <button type="button" className={favOnly ? "active" : ""} onClick={() => setFavOnly((v) => !v)}>
              收藏
            </button>
          </div>
          {error && <p className="error">{error}</p>}
          <p className="muted cv-history-count">{historyTotal} 条记录</p>
          <div className="cv-asset-list">
            {history.length === 0 && <p className="muted">还没有生成记录。出图或出视频之后会出现在这里。</p>}
            {history.map((row) => (
              <div key={row.id} className={`cv-asset-item ${row.favorite ? "is-fav" : ""}`}>
                {row.kind === "video" && row.url ? (
                  <video className="cv-asset-thumb" src={row.url} muted playsInline preload="metadata" />
                ) : row.kind === "audio" && row.url ? (
                  <audio className="cv-asset-thumb" src={row.url} controls preload="metadata" />
                ) : row.url || row.thumbnail_url ? (
                  <img className="cv-asset-thumb" src={row.thumbnail_url || row.url} alt="" />
                ) : (
                  <div className="cv-asset-thumb cv-asset-thumb-text">{(row.prompt || row.text || "文本").slice(0, 40)}</div>
                )}
                <strong>
                  {NODE_LABEL[row.node_type || ""] || row.node_type || KIND_LABEL[row.kind] || row.kind}
                  {row.favorite ? " ★" : ""}
                </strong>
                <span>
                  {KIND_LABEL[row.kind] || row.kind}
                  {row.model_name ? ` · ${row.model_name}` : ""}
                  {row.created_at ? ` · ${row.created_at.slice(0, 16).replace("T", " ")}` : ""}
                </span>
                <div className="cv-asset-actions">
                  <button type="button" className="linkish" disabled={busy} onClick={() => void sendHistory(row)}>
                    放到画布
                  </button>
                  <button type="button" className="linkish" disabled={busy} onClick={() => void toggleFav(row)}>
                    {row.favorite ? "取消收藏" : "收藏"}
                  </button>
                  <button type="button" className="linkish" disabled={busy} onClick={() => void removeHistory(row)}>
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
