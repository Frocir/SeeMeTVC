import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, type Job, type ModelOption } from "../api";
import { useAuth } from "../auth";

export default function StudioPage() {
  const { me, refresh } = useAuth();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelId, setModelId] = useState("");
  const [prompt, setPrompt] = useState("A cinematic product shot of a glass perfume bottle on wet marble, soft morning light");
  const [imageUrl, setImageUrl] = useState("");
  const [duration, setDuration] = useState(5);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<ModelOption[]>("/api/models").then((list) => {
      setModels(list);
      if (list[0]) setModelId(list[0].model_id);
    });
  }, []);

  const selected = useMemo(
    () => models.find((m) => m.model_id === modelId),
    [models, modelId],
  );
  const estimate = selected ? selected.cost_per_second * duration : 0;

  useEffect(() => {
    if (!job || job.status === "succeeded" || job.status === "failed" || job.status === "refunded") {
      return;
    }
    const t = setInterval(() => {
      void api<Job>(`/api/videos/jobs/${job.id}`).then(async (fresh) => {
        setJob(fresh);
        if (["succeeded", "failed", "refunded"].includes(fresh.status)) {
          await refresh();
        }
      });
    }, 2000);
    return () => clearInterval(t);
  }, [job, refresh]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api<Job>("/api/videos/generate", {
        method: "POST",
        body: JSON.stringify({
          model_id: modelId,
          prompt,
          image_url: imageUrl || null,
          duration_seconds: duration,
        }),
      });
      setJob(created);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="studio">
      <div className="studio-copy">
        <h1>从一句话到短片</h1>
        <p>选模型、写提示词、确认消耗后生成。只关心余额，不展示 token。</p>
      </div>

      <form className="studio-form" onSubmit={onSubmit}>
        <label>
          模型
          <select value={modelId} onChange={(e) => setModelId(e.target.value)} required>
            {models.map((m) => (
              <option key={m.model_id} value={m.model_id}>
                {m.model_id} · {m.cost_per_second}/{me?.balance_unit || "积分"}/秒
              </option>
            ))}
          </select>
        </label>
        <label>
          提示词
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={5} required />
        </label>
        <label>
          参考图 URL（可选）
          <input value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://..." />
        </label>
        <label>
          时长（秒）
          <input
            type="number"
            min={2}
            max={30}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
          />
        </label>

        <div className="estimate">
          预计消耗 <strong>{estimate.toFixed(2)}</strong> {me?.balance_unit}
          <span className="muted"> · 当前余额 {me?.balance.toFixed(2)}</span>
        </div>

        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy || !modelId}>
          {busy ? "提交中…" : "开始生成"}
        </button>
      </form>

      {job && (
        <div className="job-card">
          <div className="job-meta">
            <span>任务 #{job.id}</span>
            <span className={`status status-${job.status}`}>{job.status}</span>
          </div>
          <p>
            消耗 {job.cost.toFixed(2)} {me?.balance_unit}
            {job.balance_after != null && <> · 余额变为 {job.balance_after.toFixed(2)}</>}
          </p>
          {job.error_message && <p className="error">{job.error_message}</p>}
          {job.result_url && (
            <>
              <video src={job.result_url} controls playsInline className="result-video" />
              <p className="muted">
                当前若为 mock 渠道，播放的是演示片；接入真实 fal Key 后才会出 Seedance 成片。
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
