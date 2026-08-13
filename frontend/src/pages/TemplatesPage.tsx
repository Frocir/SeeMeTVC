import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import BeautyPromoGallery from "../components/BeautyPromoGallery";
import { api, type ModelOption } from "../api";
import type { BeautyPromo } from "../beautyAssets";
import { createDraft } from "../workflow/createDraft";
import { WF_TEMPLATES, type WfTemplateId } from "../workflow/templates";

export default function TemplatesPage() {
  const navigate = useNavigate();
  const [modelId, setModelId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api<ModelOption[]>("/api/models")
      .then((ms) => setModelId(ms[0]?.model_id || ""))
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  async function useTpl(id: WfTemplateId, name?: string, prompt?: string, brand?: string) {
    setBusy(true);
    setError("");
    try {
      const wf = await createDraft({
        name: name || WF_TEMPLATES.find((t) => t.id === id)?.name || "未命名项目",
        template: id,
        modelId,
        brand,
        prompt,
      });
      navigate(`/workflow/${wf.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  function onPromo(promo: BeautyPromo) {
    void useTpl("quick_shot", promo.title, promo.prompt, promo.brand);
  }

  return (
    <section>
      <div className="page-head">
        <p className="eyebrow">Templates + Lookbook</p>
        <h1>模板</h1>
        <p className="lead">官方模板与 Lookbook 同款。选用后新建项目并打开编辑，提示词写入 Brief。</p>
      </div>
      {error && <p className="error">{error}</p>}
      <h2 className="block-title">官方模板</h2>
      <div className="tpl-grid">
        {WF_TEMPLATES.map((t) => (
          <article key={t.id} className="tpl-card">
            <h3>{t.name}</h3>
            <p className="ver">{t.hint}</p>
            <p className="muted" style={{ fontSize: "0.75rem" }}>
              id: <code>{t.id}</code>
            </p>
            <button
              className="primary"
              type="button"
              disabled={busy}
              style={{ marginTop: 10 }}
              onClick={() => void useTpl(t.id)}
            >
              用此模板新建项目
            </button>
          </article>
        ))}
      </div>
      <BeautyPromoGallery
        title="Lookbook 同款"
        subtitle="点选后新建项目，并把镜头提示词写入 Brief"
        onPick={onPromo}
      />
    </section>
  );
}
