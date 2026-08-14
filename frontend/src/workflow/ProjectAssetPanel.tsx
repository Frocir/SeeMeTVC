import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  uploadFile,
  type ProjectAsset,
  type Workflow,
} from "../api";
import { type WfNodeType } from "./types";
type KindFilter = "all" | "image" | "video" | "audio" | "output";

const KIND_LABEL: Record<string, string> = {
  image: "图",
  video: "视频",
  audio: "音频",
  output: "成片",
};

export default function ProjectAssetPanel({
  workflowId,
  reloadKey = 0,
  onPlace,
}: {
  workflowId: number;
  reloadKey?: number;
  onPlace: (kind: WfNodeType, url: string, label: string) => void;
}) {
  const [items, setItems] = useState<ProjectAsset[]>([]);
  const [projects, setProjects] = useState<Workflow[]>([]);
  const [filter, setFilter] = useState<KindFilter>("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copyId, setCopyId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function reload() {
    const [assets, wfs] = await Promise.all([
      api<ProjectAsset[]>(`/api/workflows/${workflowId}/assets`),
      api<Workflow[]>("/api/workflows"),
    ]);
    setItems(assets);
    setProjects(wfs.filter((w) => w.id !== workflowId));
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof Error ? e.message : "加载素材失败"));
  }, [workflowId, reloadKey]);

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
      await reload();
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

  return (
    <div className="cv-section">
      <p className="eyebrow">本项目素材</p>
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
        <span>直接进本项目库</span>
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
                放到节点
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
    </div>
  );
}
