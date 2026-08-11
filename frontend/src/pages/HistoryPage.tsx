import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  isActiveJob,
  isActiveRun,
  STATUS_LABEL,
  type Job,
  type WorkflowRun,
} from "../api";
import { useAuth } from "../auth";

type Filter = "all" | "succeeded" | "active" | "other";
type SourceFilter = "all" | "studio" | "canvas";

type HistoryItem = {
  key: string;
  kind: "studio" | "canvas";
  id: number;
  title: string;
  subtitle: string;
  status: string;
  cost: number;
  balance_after: number | null;
  result_url: string | null;
  error_message: string | null;
  created_at: string;
  duration_seconds?: number;
  image_url?: string | null;
};

function runTitle(run: WorkflowRun): string {
  const nodes = run.graph?.nodes || [];
  for (const n of nodes) {
    const data = (n.data || {}) as Record<string, unknown>;
    for (const key of ["prompt", "text", "slogan", "brand"] as const) {
      const v = data[key];
      if (typeof v === "string" && v.trim()) return v.trim();
    }
  }
  return `画布运行 #${run.id}`;
}

function fromJob(j: Job): HistoryItem {
  return {
    key: `job-${j.id}`,
    kind: "studio",
    id: j.id,
    title: j.prompt,
    subtitle: j.model_id,
    status: j.status,
    cost: j.cost,
    balance_after: j.balance_after,
    result_url: j.result_url,
    error_message: j.error_message,
    created_at: j.created_at,
    duration_seconds: j.duration_seconds,
    image_url: j.image_url,
  };
}

function fromRun(r: WorkflowRun): HistoryItem {
  return {
    key: `run-${r.id}`,
    kind: "canvas",
    id: r.id,
    title: runTitle(r),
    subtitle: r.workflow_id != null ? `工作流 #${r.workflow_id}` : "临时画布",
    status: r.status,
    cost: r.cost,
    balance_after: r.balance_after,
    result_url: r.result_url,
    error_message: r.error_message,
    created_at: r.created_at,
  };
}

function isActiveItem(item: HistoryItem) {
  return item.kind === "studio" ? isActiveJob(item.status) : isActiveRun(item.status);
}

export default function HistoryPage() {
  const { me } = useAuth();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [source, setSource] = useState<SourceFilter>("all");
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void Promise.all([
      api<Job[]>("/api/videos/jobs?limit=100"),
      api<WorkflowRun[]>("/api/workflows/runs?limit=100"),
    ])
      .then(([jobs, runs]) => {
        const merged = [...jobs.map(fromJob), ...runs.map(fromRun)].sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        );
        setItems(merged);
        const firstPlayable = merged.find((x) => x.status === "succeeded" && x.result_url);
        if (firstPlayable) setExpandedKey(firstPlayable.key);
      })
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    let list = items;
    if (source !== "all") list = list.filter((x) => x.kind === source);
    if (filter === "succeeded") return list.filter((j) => j.status === "succeeded");
    if (filter === "active") return list.filter((j) => isActiveItem(j));
    if (filter === "other") {
      return list.filter((j) => j.status === "failed" || j.status === "refunded" || j.status === "cancelled");
    }
    return list;
  }, [items, filter, source]);

  const works = useMemo(
    () => items.filter((j) => j.status === "succeeded" && j.result_url),
    [items],
  );

  return (
    <section className="history">
      <div className="page-head">
        <p className="eyebrow">成片档案</p>
        <h1>我的美妆广告片</h1>
        <p className="lead">回看工作室快出片与画布编排成片、提示词与余额变化。</p>
      </div>

      {works.length > 0 && (
        <div className="works-gallery">
          <div className="works-gallery-head">
            <h2>品牌成片墙</h2>
            <span className="muted">{works.length} 部成片</span>
          </div>
          <div className="works-grid">
            {works.map((j) => (
              <article key={j.key} className={`work-card${expandedKey === j.key ? " active" : ""}`}>
                <button
                  type="button"
                  className="work-card-hit"
                  onClick={() => setExpandedKey(expandedKey === j.key ? null : j.key)}
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
                    <span className="work-card-id">
                      {j.kind === "studio" ? "工作室" : "画布"} #{j.id}
                    </span>
                    <span className="muted">{j.subtitle}</span>
                  </div>
                  <p className="work-card-prompt">{j.title}</p>
                </button>
                {expandedKey === j.key && (
                  <div className="work-player">
                    <video src={j.result_url!} controls playsInline autoPlay className="work-video" />
                    <p className="muted">
                      {new Date(j.created_at).toLocaleString()} · 消耗 {j.cost.toFixed(2)}{" "}
                      {me?.balance_unit}
                      {j.balance_after != null && <> · 余额 {j.balance_after.toFixed(2)}</>}
                      {j.kind === "canvas" && (
                        <>
                          {" · "}
                          <Link to="/workflow">打开画布</Link>
                        </>
                      )}
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
        <div className="history-toolbar-filters">
          <div className="filter-tabs">
            {(
              [
                ["all", "全部来源"],
                ["studio", "工作室"],
                ["canvas", "画布"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`filter-tab${source === key ? " active" : ""}`}
                onClick={() => setSource(key)}
              >
                {label}
              </button>
            ))}
          </div>
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
      </div>

      {loading ? (
        <p className="muted empty">加载中…</p>
      ) : (
        <div className="history-list">
          {filtered.map((j) => {
            const open = expandedKey === j.key;
            return (
              <article key={j.key} className={`history-item${open ? " open" : ""}`}>
                <button
                  type="button"
                  className="history-item-row"
                  onClick={() => setExpandedKey(open ? null : j.key)}
                >
                  <span className="history-item-main">
                    <strong>
                      {j.kind === "studio" ? "工作室" : "画布"} #{j.id}
                    </strong>
                    <span className="muted">{new Date(j.created_at).toLocaleString()}</span>
                    <span className="history-item-prompt">{j.title}</span>
                  </span>
                  <span className="history-item-side">
                    <span className="muted">{j.subtitle}</span>
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
                    <p>{j.title}</p>
                    <p className="muted">
                      来源：{j.kind === "studio" ? "工作室快出片" : "画布编排"}
                      {j.duration_seconds != null && <> · 时长 {j.duration_seconds}s</>}
                      {j.balance_after != null && <> · 余额变为 {j.balance_after.toFixed(2)}</>}
                      {j.image_url && (
                        <>
                          <br />
                          参考图：{j.image_url}
                        </>
                      )}
                      {j.kind === "canvas" && (
                        <>
                          <br />
                          <Link to="/workflow">回到画布继续编辑</Link>
                        </>
                      )}
                    </p>
                    {j.error_message && <p className="error">{j.error_message}</p>}
                    {j.result_url && (
                      <video src={j.result_url} controls playsInline className="history-video" />
                    )}
                    {!j.result_url && isActiveItem(j) && (
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
