import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type ModelOption } from "../api";
import { createDraft } from "../workflow/createDraft";

export default function CharactersPage() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [modelId, setModelId] = useState("");

  useEffect(() => {
    void api<ModelOption[]>("/api/models")
      .then((ms) => setModelId(ms[0]?.model_id || ""))
      .catch(() => undefined);
  }, []);

  async function openLinear() {
    setBusy(true);
    setError("");
    try {
      const wf = await createDraft({
        name: "美妆线性链路",
        template: "beauty_linear",
        modelId,
      });
      navigate(`/workflow/${wf.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="empty-panel">
        <p className="eyebrow">人物资产库</p>
        <h1>一级人物库本轮尚未开放</h1>
        <p className="lead">
          人物库本轮空着。请在项目里的 <strong>妆造图</strong> 节点上传肖像，或到左侧{" "}
          <strong>素材</strong> Tab 上传图片。
        </p>
        {error && <p className="error">{error}</p>}
        <div className="empty-actions">
          <Link className="secondary" to="/">
            回到工作区
          </Link>
          <button className="primary" type="button" disabled={busy} onClick={() => void openLinear()}>
            用美妆线性链路新建项目
          </button>
        </div>
      </div>
    </section>
  );
}
