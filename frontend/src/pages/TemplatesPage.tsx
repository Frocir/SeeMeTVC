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
      .then((ms) =>
        setModelId(ms.find((m) => m.model_id === "seedance-2.5")?.model_id || ms[0]?.model_id || ""),
      )
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
    void useTpl(
      promo.kind === "hardware" ? "hardware_quick" : "quick_shot",
      promo.title,
      promo.prompt,
      promo.brand,
    );
  }

  return (
    <section>
      <div className="page-head">
        <p className="eyebrow">Templates + Lookbook</p>
        <h1>模板</h1>
        <p className="lead">美学短片和硬件科创都能用。选一套流程，或从 Lookbook 点一张图开始。</p>
      </div>
      {error && <p className="error">{error}</p>}
      {(
        [
          ["beauty", "美学"],
          ["hardware", "硬件 / 科创"],
        ] as const
      ).map(([kind, title]) => (
        <div key={kind}>
          <h2 className="block-title">{title}</h2>
          <div className="tpl-grid">
            {WF_TEMPLATES.filter((t) => t.kind === kind).map((t) => (
              <article key={t.id} className="tpl-card">
                <h3>{t.name}</h3>
                <p className="ver">{t.hint}</p>
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
        </div>
      ))}
      <BeautyPromoGallery
        title="Lookbook 同款"
        subtitle="点选后新建项目，并把画面描述写进文案"
        onPick={onPromo}
      />
    </section>
  );
}
