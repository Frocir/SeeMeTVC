import { useEffect, useMemo, useState } from "react";
import { api, isActiveJob, STATUS_LABEL, type Job } from "../api";
import { useAuth } from "../auth";

type Filter = "all" | "succeeded" | "active" | "other";

export default function HistoryPage() {
  const { me } = useAuth();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void api<Job[]>("/api/videos/jobs?limit=100")
      .then((list) => {
        setJobs(list);
        const firstPlayable = list.find((j) => j.status === "succeeded" && j.result_url);
        if (firstPlayable) setExpandedId(firstPlayable.id);
      })
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    if (filter === "succeeded") return jobs.filter((j) => j.status === "succeeded");
    if (filter === "active") return jobs.filter((j) => isActiveJob(j.status));
    if (filter === "other") {
      return jobs.filter((j) => j.status === "failed" || j.status === "refunded");
    }
    return jobs;
  }, [jobs, filter]);

  const works = useMemo(
    () => jobs.filter((j) => j.status === "succeeded" && j.result_url),
    [jobs],
  );

  return (
    <section className="history">
      <div className="page-head">
        <p className="eyebrow">成片档案</p>
        <h1>我的美妆广告片</h1>
        <p className="lead">回看已生成的面部美妆 TVC、提示词与余额变化。</p>
      </div>

      {works.length > 0 && (
        <div className="works-gallery">
          <div className="works-gallery-head">
            <h2>品牌成片墙</h2>
            <span className="muted">{works.length} 部成片</span>
          </div>
          <div className="works-grid">
            {works.map((j) => (
              <article
                key={j.id}
                className={`work-card${expandedId === j.id ? " active" : ""}`}
              >
                <button
                  type="button"
                  className="work-card-hit"
                  onClick={() => setExpandedId(expandedId === j.id ? null : j.id)}
                >
                  <video
                    src={j.result_url!}
                    muted
                    playsInline
                    preload="metadata"
                    className="work-thumb"
                    onMouseEnter={(e) => void e.currentTarget.play().catch(() => undefined)}
                    onMouseLeave={(e) => {
                      e.currentTarget.pause();
                      e.currentTarget.currentTime = 0;
                    }}
                  />
                  <div className="work-card-meta">
                    <span className="work-card-id">#{j.id}</span>
                    <span className="muted">{j.model_id}</span>
                  </div>
                  <p className="work-card-prompt">{j.prompt}</p>
                </button>
                {expandedId === j.id && (
                  <div className="work-player">
                    <video src={j.result_url!} controls playsInline autoPlay className="work-video" />
                    <p className="muted">
                      {new Date(j.created_at).toLocaleString()} · 消耗 {j.cost.toFixed(2)}{" "}
                      {me?.balance_unit}
                      {j.balance_after != null && <> · 余额 {j.balance_after.toFixed(2)}</>}
                    </p>
                  </div>
                )}
              </article>
            ))}
          </div>
        </div>
      )}

      <div className="history-toolbar">
        <h2>全部任务</h2>
        <div className="filter-tabs">
          {(
            [
              ["all", "全部"],
              ["succeeded", "已完成"],
              ["active", "进行中"],
              ["other", "失败/退款"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`filter-tab${filter === key ? " active" : ""}`}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="muted empty">加载中…</p>
      ) : (
        <div className="history-list">
          {filtered.map((j) => {
            const open = expandedId === j.id;
            return (
              <article key={j.id} className={`history-item${open ? " open" : ""}`}>
                <button
                  type="button"
                  className="history-item-row"
                  onClick={() => setExpandedId(open ? null : j.id)}
                >
                  <span className="history-item-main">
                    <strong>#{j.id}</strong>
                    <span className="muted">{new Date(j.created_at).toLocaleString()}</span>
                    <span className="history-item-prompt">{j.prompt}</span>
                  </span>
                  <span className="history-item-side">
                    <span className="muted">{j.model_id}</span>
                    <span className={`status status-${j.status}`}>
                      {STATUS_LABEL[j.status] || j.status}
                    </span>
                    <span>
                      -{j.cost.toFixed(2)} {me?.balance_unit}
                    </span>
                  </span>
                </button>
                {open && (
                  <div className="history-item-detail">
                    <p>{j.prompt}</p>
                    <p className="muted">
                      时长 {j.duration_seconds}s
                      {j.balance_after != null && <> · 余额变为 {j.balance_after.toFixed(2)}</>}
                      {j.image_url && (
                        <>
                          <br />
                          参考图：{j.image_url}
                        </>
                      )}
                    </p>
                    {j.error_message && <p className="error">{j.error_message}</p>}
                    {j.result_url && (
                      <video src={j.result_url} controls playsInline className="history-video" />
                    )}
                    {!j.result_url && isActiveJob(j.status) && (
                      <p className="muted">生成进行中，完成后可在此回看。</p>
                    )}
                  </div>
                )}
              </article>
            );
          })}
          {filtered.length === 0 && <p className="muted empty">暂无记录</p>}
        </div>
      )}
    </section>
  );
}
