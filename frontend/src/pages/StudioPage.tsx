import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useShowAdmin } from "../flags";
import {
  api,
  isActiveJob,
  isTerminalJob,
  STATUS_LABEL,
  type Job,
  type ModelOption,
  type ParallelQuota,
} from "../api";
import { useAuth } from "../auth";
import { DEFAULT_VIDEO_MODEL_ID } from "../videoIds";
import { BEAUTY_PROMOS, type BeautyPromo } from "../beautyAssets";
import BeautyPromoGallery from "../components/BeautyPromoGallery";
import ReferenceImageField from "../components/ReferenceImageField";
import { ensureUpstreamImageUrl } from "../imageUrl";

function upsertJob(list: Job[], fresh: Job) {
  const idx = list.findIndex((j) => j.id === fresh.id);
  if (idx === -1) return [fresh, ...list];
  const next = list.slice();
  next[idx] = fresh;
  return next;
}

export default function StudioPage() {
  const { me, refresh } = useAuth();
  const showAdmin = useShowAdmin();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelId, setModelId] = useState("");
  const [prompt, setPrompt] = useState(BEAUTY_PROMOS[0].prompt);
  const [imageUrl, setImageUrl] = useState("");
  const [duration, setDuration] = useState(BEAUTY_PROMOS[0].duration);
  const [activeTemplate, setActiveTemplate] = useState(BEAUTY_PROMOS[0].id);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [quota, setQuota] = useState<ParallelQuota | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadQuota = useCallback(async () => {
    const q = await api<ParallelQuota>("/api/videos/parallel-quota");
    setQuota(q);
  }, []);

  useEffect(() => {
    void Promise.all([
      api<ModelOption[]>("/api/models"),
      api<Job[]>("/api/videos/jobs?limit=20"),
      api<ParallelQuota>("/api/videos/parallel-quota"),
    ]).then(([list, recent, q]) => {
      setModels(list);
      if (list[0]) {
        setModelId(list.find((m) => m.model_id === DEFAULT_VIDEO_MODEL_ID)?.model_id || list[0].model_id);
      }
      setJobs(recent);
      setQuota(q);
      // Only auto-open in-progress jobs; finished clips stay in the queue so the gallery stays visible.
      const active = recent.find((j) => isActiveJob(j.status));
      if (active) setSelectedId(active.id);
    });
  }, []);

  const selected = useMemo(() => models.find((m) => m.model_id === modelId), [models, modelId]);
  const estimate = selected ? selected.cost_per_second * duration : 0;
  const activeJobs = useMemo(() => jobs.filter((j) => isActiveJob(j.status)), [jobs]);
  const sessionJobs = useMemo(() => jobs.slice(0, 12), [jobs]);
  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selectedId) ?? null,
    [jobs, selectedId],
  );
  const atParallelLimit = quota != null && quota.available <= 0;

  useEffect(() => {
    if (activeJobs.length === 0) return;
    const t = setInterval(() => {
      void Promise.all(
        activeJobs.map((j) => api<Job>(`/api/videos/jobs/${j.id}`).catch(() => null)),
      ).then(async (freshList) => {
        let finished = false;
        setJobs((prev) => {
          let next = prev;
          for (const fresh of freshList) {
            if (!fresh) continue;
            next = upsertJob(next, fresh);
            if (isTerminalJob(fresh.status)) finished = true;
          }
          return next;
        });
        if (finished) {
          await refresh();
          await loadQuota();
        }
      });
    }, 2000);
    return () => clearInterval(t);
  }, [activeJobs, refresh, loadQuota]);

  function applyPromo(promo: BeautyPromo) {
    setActiveTemplate(promo.id);
    setPrompt(promo.prompt);
    setDuration(promo.duration);
    // Same-origin path only; submit re-uploads so Agnes can consume the bytes.
    setImageUrl(promo.image);
    setSelectedId(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const resolvedImage = await ensureUpstreamImageUrl(imageUrl || null);
      if (resolvedImage && resolvedImage !== imageUrl) {
        setImageUrl(resolvedImage);
      }
      const created = await api<Job>("/api/videos/generate", {
        method: "POST",
        body: JSON.stringify({
          model_id: modelId,
          prompt,
          image_url: resolvedImage,
          duration_seconds: duration,
        }),
      });
      setJobs((prev) => upsertJob(prev, created));
      setSelectedId(created.id);
      await refresh();
      await loadQuota();
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
      await loadQuota();
    } finally {
      setBusy(false);
    }
  }

  const submitLabel = busy
    ? "提交中…"
    : atParallelLimit
      ? `并行已满（${quota?.max_parallel}）`
      : activeJobs.length > 0
        ? `并行出片（${activeJobs.length}/${quota?.max_parallel ?? "…"}）`
        : "生成美妆广告片";

  return (
    <section className="studio-stage">
      <aside className="studio-rail">
        <p className="eyebrow">美妆 TVC</p>
        <h1>面部成片工作室</h1>
        <p className="lead">
          专为唇妆、底妆、护肤广告片设计。点选宣传素材即可填入镜头提示词，最多并行{" "}
          {quota?.max_parallel ?? 3} 路。
        </p>

        <div className="template-strip">
          {BEAUTY_PROMOS.slice(0, 6).map((p) => (
            <button
              key={p.id}
              type="button"
              className={`template-chip${activeTemplate === p.id ? " active" : ""}`}
              onClick={() => applyPromo(p)}
            >
              {p.tag}
            </button>
          ))}
        </div>

        <form className="studio-form" onSubmit={onSubmit}>
          {models.length === 0 && (
            <div className="empty-hint" role="status">
              <strong>暂无可用模型</strong>
              <p className="muted">
                请超管在「超管」页对 Seedance Lite / Fast / 2.5 填写<strong>火山方舟 ARK_API_KEY</strong>并启用。
              </p>
              {showAdmin && me?.role === "super_admin" && (
                <Link className="linkish" to="/admin">
                  去超管启用渠道 →
                </Link>
              )}
            </div>
          )}
          <label>
            模型
            <select
              value={modelId}
              onChange={(e) => {
                const mid = e.target.value;
                setModelId(mid);
                const m = models.find((x) => x.model_id === mid);
                if (m?.duration_min != null && m?.duration_max != null) {
                  setDuration((d) => Math.max(m.duration_min!, Math.min(m.duration_max!, d)));
                }
              }}
              required
              disabled={models.length === 0}
            >
              {models.length === 0 && <option value="">（无可用模型）</option>}
              {models.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.label || m.model_id}
                  {m.supports_audio ? " · 有声" : ""}
                  {m.provider === "agnes" || m.provider === "pavo" ? " · 免费 Pavo" : ""}
                  {" · "}
                  {m.cost_per_second}/{me?.balance_unit || "积分"}/秒
                </option>
              ))}
            </select>
          </label>

          <label>
            镜头提示词
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={6} required />
          </label>

          <ReferenceImageField
            value={imageUrl}
            onChange={setImageUrl}
            label="参考图（可选）"
            hint="可点右侧素材填入，或本地上传 / 粘贴 URL"
            placeholder="产品静帧 / 面部参考图"
          />

          <label>
            时长（秒）
            <input
              type="number"
              min={selected?.duration_min ?? 2}
              max={selected?.duration_max ?? 30}
              step={1}
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              onBlur={() => {
                const lo = selected?.duration_min ?? 2;
                const hi = selected?.duration_max ?? 30;
                setDuration((d) => Math.max(lo, Math.min(hi, d)));
              }}
            />
          </label>
          {selected && (
            <p className="muted" style={{ marginTop: "-0.5rem" }}>
              有效时长 <strong>{selected.duration_min ?? 2}–{selected.duration_max ?? 30} 秒</strong>
              {selected.model_id === "seedance-2.5"
                ? "（方舟 2.x 最短约 4 秒；填更短会按下限生成并计费）"
                : selected.model_id === "seedance-fast"
                  ? "（方舟 Fast 约 4–15 秒；超出自动夹紧）"
                  : selected.model_id === "seedance-lite"
                    ? "（方舟 Lite 约 2–12 秒；超出自动夹紧）"
                    : "（超出自动夹紧）"}
              {selected.supports_audio ? " · 有声" : " · 无原生音频"}
              {selected.model_id === "seedance-lite" ||
              selected.model_id === "seedance-fast" ||
              selected.model_id === "seedance-2.5"
                ? " · 有参考图走图生，否则文生"
                : ""}
            </p>
          )}

          <div className="estimate">
            <span>
              预计 <strong>{estimate.toFixed(2)}</strong> {me?.balance_unit}
            </span>
            <span className="muted">
              余额 {me?.balance.toFixed(2)} · 并行空位 {quota?.available ?? "—"}/
              {quota?.max_parallel ?? "—"}
            </span>
          </div>

          {error && <p className="error">{error}</p>}
          <button
            type="submit"
            className="block primary"
            disabled={busy || !modelId || atParallelLimit || models.length === 0}
          >
            {models.length === 0 ? "请先启用模型" : submitLabel}
          </button>
        </form>

        {sessionJobs.length > 0 && (
          <div className="job-queue">
            <div className="job-queue-head">
              <span>任务队列</span>
              <span className="muted">{activeJobs.length} 进行中</span>
            </div>
            <ul className="job-queue-list">
              {sessionJobs.map((j) => (
                <li key={j.id}>
                  <button
                    type="button"
                    className={`job-queue-item${selectedId === j.id ? " active" : ""}`}
                    onClick={() => setSelectedId(j.id)}
                  >
                    <span className="job-queue-id">#{j.id}</span>
                    <span className={`status status-${j.status}`}>
                      {STATUS_LABEL[j.status] || j.status}
                    </span>
                    <span className="job-queue-prompt">{j.prompt}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>

      <div className="studio-canvas">
        <div className="canvas-frame">
          {selectedJob?.result_url ? (
            <div className="canvas-panel">
              <div className="job-meta">
                <span>
                  任务 #{selectedJob.id} · {selectedJob.model_id}
                </span>
                <span className={`status status-${selectedJob.status}`}>
                  {STATUS_LABEL[selectedJob.status] || selectedJob.status}
                </span>
                <button type="button" className="ghost canvas-back" onClick={() => setSelectedId(null)}>
                  ← 回到素材
                </button>
              </div>
              <video
                key={selectedJob.id}
                src={selectedJob.result_url}
                controls
                playsInline
                autoPlay
                className="result-video"
              />
              <p className="job-note">
                {selectedJob.prompt}
                <br />
                消耗 {selectedJob.cost.toFixed(2)} {me?.balance_unit}
                {selectedJob.balance_after != null && (
                  <> · 余额变为 {selectedJob.balance_after.toFixed(2)}</>
                )}
              </p>
            </div>
          ) : selectedJob ? (
            <div className="canvas-panel">
              <div className="job-meta">
                <span>
                  任务 #{selectedJob.id} · {selectedJob.model_id}
                </span>
                <span className={`status status-${selectedJob.status}`}>
                  {STATUS_LABEL[selectedJob.status] || selectedJob.status}
                </span>
                <button type="button" className="ghost canvas-back" onClick={() => setSelectedId(null)}>
                  ← 回到素材
                </button>
              </div>
              <div className="canvas-placeholder">
                <div className="mark">▶</div>
                <h2>{isActiveJob(selectedJob.status) ? "妆效画面生成中" : "暂无成片"}</h2>
                <p>{selectedJob.prompt}</p>
                <p>
                  消耗 {selectedJob.cost.toFixed(2)} {me?.balance_unit}
                  {selectedJob.balance_after != null && (
                    <> · 余额变为 {selectedJob.balance_after.toFixed(2)}</>
                  )}
                </p>
                {selectedJob.error_message && <p className="error">{selectedJob.error_message}</p>}
              </div>
            </div>
          ) : (
            <div className="canvas-panel">
              <div className="canvas-placeholder">
                <div className="mark">▶</div>
                <h2>从美妆宣传素材开拍</h2>
                <p>下方为面部美妆 TVC 样例素材（公开图源占位）。点击卡片即可填入提示词与参考图。</p>
              </div>
              <BeautyPromoGallery compact onPick={applyPromo} />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
