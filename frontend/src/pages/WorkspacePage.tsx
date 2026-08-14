import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, STATUS_LABEL, type ModelOption, type Workflow, type WorkflowRun } from "../api";
import { createDraft } from "../workflow/createDraft";
import { graphAspect, graphBrand } from "../workflow/draftMeta";
import { WF_TEMPLATES, type WfTemplateId } from "../workflow/templates";

type Filter = "all" | "wip" | "done";

function isVideoCover(url: string) {
  return /\.(mp4|webm|mov)(\?|$)/i.test(url);
}

function lastRunOf(wfId: number, runs: WorkflowRun[]): WorkflowRun | undefined {
  return runs.find((r) => r.workflow_id === wfId);
}

function isDone(run?: WorkflowRun) {
  return run?.status === "succeeded";
}

export default function WorkspacePage() {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [menu, setMenu] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState(false);
  const [newName, setNewName] = useState("");
  const [newBrand, setNewBrand] = useState("SeeMe");
  const [newMode, setNewMode] = useState<"blank" | "template">("blank");
  const [newTpl, setNewTpl] = useState<WfTemplateId>("beauty_linear");

  const modelId = models[0]?.model_id || "";

  async function reload() {
    const [wfs, rs, ms] = await Promise.all([
      api<Workflow[]>("/api/workflows"),
      api<WorkflowRun[]>("/api/workflows/runs?limit=100"),
      api<ModelOption[]>("/api/models"),
    ]);
    setDrafts(wfs);
    setRuns(rs);
    setModels(ms);
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return drafts.filter((wf) => {
      const brand = wf.brand || graphBrand(wf.graph);
      if (q && !(`${wf.name} ${brand}`).toLowerCase().includes(q)) return false;
      const run = lastRunOf(wf.id, runs);
      if (filter === "done") return isDone(run);
      if (filter === "wip") return !isDone(run);
      return true;
    });
  }, [drafts, runs, query, filter]);

  async function openNew(template: WfTemplateId, name: string, brand?: string, prompt?: string) {
    setBusy(true);
    setError("");
    try {
      const wf = await createDraft({ name, template, modelId, brand, prompt });
      navigate(`/workflow/${wf.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function duplicate(wf: Workflow) {
    setBusy(true);
    setError("");
    try {
      const copy = await api<Workflow>("/api/workflows", {
        method: "POST",
        body: JSON.stringify({ name: `${wf.name} 副本`, brand: wf.brand, graph: wf.graph }),
      });
      setMenu(null);
      await reload();
      navigate(`/workflow/${copy.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "复制失败");
    } finally {
      setBusy(false);
    }
  }

  async function remove(wf: Workflow) {
    if (!window.confirm(`删除项目「${wf.name}」？画布、成片和素材都会删掉，且不可恢复。`)) {
      setMenu(null);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(`/api/workflows/${wf.id}`, { method: "DELETE" });
      setMenu(null);
      setDrafts((xs) => xs.filter((x) => x.id !== wf.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workspace-page">
      <div className="heading">
        <div>
          <p className="eyebrow">工作区</p>
          <h1>我的项目</h1>
          <p className="lead">每个项目一张编辑画布。封面优先用成片，还没有成片时用最后一张图片。</p>
        </div>
        <button className="primary" type="button" onClick={() => setModal(true)}>
          ＋ 新建项目
        </button>
      </div>

      <div className="filterbar">
        <label className="search">
          ⌕
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索项目或品牌"
          />
        </label>
        <div className="filters">
          <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
            <option value="all">全部状态</option>
            <option value="wip">进行中</option>
            <option value="done">已完成</option>
          </select>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="project-grid">
        <button className="new-card" type="button" onClick={() => setModal(true)}>
          <span className="new-mark">＋</span>
          <strong>新建项目</strong>
          <span>空白项目或官方模板</span>
        </button>
        {list.map((wf) => {
          const brand = wf.brand || graphBrand(wf.graph);
          const aspect = graphAspect(wf.graph);
          const run = lastRunOf(wf.id, runs);
          const status = run?.status || "draft";
          const statusText = status === "draft" ? "未出片" : STATUS_LABEL[status] || status;
          const thumb = wf.cover_url || "";
          const thumbIsVideo = thumb ? isVideoCover(thumb) : false;
          return (
            <article key={wf.id} className="project-card">
              <button
                type="button"
                className="project-card-hit"
                onClick={() => navigate(`/workflow/${wf.id}`)}
              >
                <div className={`thumb ${aspect === "9:16" ? "a916" : aspect === "1:1" ? "a11" : "a169"}`}>
                  {thumb ? (
                    thumbIsVideo ? (
                      <video className="thumb-media" src={thumb} muted playsInline preload="metadata" />
                    ) : (
                      <img className="thumb-media" src={thumb} alt="" />
                    )
                  ) : null}
                  <span className="thumb-corner">{aspect}</span>
                </div>
              </button>
              <div className="card-info">
                <div className="card-title">
                  <button type="button" className="linkish-title" onClick={() => navigate(`/workflow/${wf.id}`)}>
                    {wf.name}
                  </button>
                  <button
                    className="more"
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setMenu(menu === wf.id ? null : wf.id);
                    }}
                  >
                    ⋯
                  </button>
                </div>
                {menu === wf.id && (
                  <div className="more-menu">
                    <button type="button" disabled={busy} onClick={() => void duplicate(wf)}>
                      复制项目
                    </button>
                    <button type="button" className="danger-btn" disabled={busy} onClick={() => void remove(wf)}>
                      删除
                    </button>
                  </div>
                )}
                <div className="card-meta">
                  <span>{brand}</span>
                  <span>{new Date(wf.updated_at).toLocaleString()}</span>
                </div>
                <div className="card-status">
                  <span className={`status status-${status}`}>{statusText}</span>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {modal && (
        <div className="modal-back" onClick={() => setModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>新建项目</h2>
            <label>
              名称
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="例如：秋季底妆新品 TVC"
              />
            </label>
            <label>
              品牌
              <input value={newBrand} onChange={(e) => setNewBrand(e.target.value)} />
            </label>
            <label>起始方式</label>
            <div className="mode-grid">
              <button
                type="button"
                className={`mode-card${newMode === "blank" ? " active" : ""}`}
                onClick={() => setNewMode("blank")}
              >
                <strong>＋ 空白项目</strong>
                <small>无声快出（Brief → LLM → 文生图 → 图生）</small>
              </button>
              <button
                type="button"
                className={`mode-card${newMode === "template" ? " active" : ""}`}
                onClick={() => setNewMode("template")}
              >
                <strong>▣ 官方模板</strong>
                <small>预填官方美妆节点</small>
              </button>
            </div>
            {newMode === "template" && (
              <label>
                模板
                <select value={newTpl} onChange={(e) => setNewTpl(e.target.value as WfTemplateId)}>
                  {WF_TEMPLATES.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="modal-actions">
              <button className="ghost" type="button" onClick={() => setModal(false)}>
                取消
              </button>
              <button
                className="primary"
                type="button"
                disabled={busy}
                onClick={() =>
                  void openNew(
                    newMode === "template" ? newTpl : "quick_shot",
                    newName.trim() || "未命名项目",
                    newBrand.trim() || "SeeMe",
                  )
                }
              >
                创建并打开
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
