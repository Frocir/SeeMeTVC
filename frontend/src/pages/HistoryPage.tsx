import { useEffect, useState } from "react";
import { api, type Job } from "../api";
import { useAuth } from "../auth";

export default function HistoryPage() {
  const { me } = useAuth();
  const [jobs, setJobs] = useState<Job[]>([]);

  useEffect(() => {
    void api<Job[]>("/api/videos/jobs").then(setJobs);
  }, []);

  return (
    <section className="history">
      <h1>生成记录</h1>
      <p className="muted">只展示消耗与余额变化，便于理解。</p>
      <div className="table">
        <div className="row head">
          <span>时间</span>
          <span>模型</span>
          <span>状态</span>
          <span>消耗</span>
          <span>余额</span>
        </div>
        {jobs.map((j) => (
          <div className="row" key={j.id}>
            <span>{new Date(j.created_at).toLocaleString()}</span>
            <span>{j.model_id}</span>
            <span className={`status status-${j.status}`}>{j.status}</span>
            <span>
              -{j.cost.toFixed(2)} {me?.balance_unit}
            </span>
            <span>
              {j.balance_after != null ? j.balance_after.toFixed(2) : "—"} {me?.balance_unit}
            </span>
          </div>
        ))}
        {jobs.length === 0 && <p className="muted empty">暂无记录</p>}
      </div>
    </section>
  );
}
