import { useMemo, useState } from "react";
import { LOOKBOOK_PROMOS, LOOKBOOK_TAGS, type BeautyPromo } from "../beautyAssets";

type Props = {
  onPick?: (promo: BeautyPromo) => void;
  compact?: boolean;
  title?: string;
  subtitle?: string;
};

export default function BeautyPromoGallery({
  onPick,
  compact = false,
  title = "美妆 TVC 宣传素材",
  subtitle = "点击素材可填入提示词，快速开拍唇妆 / 底妆 / 护肤广告片",
}: Props) {
  const [tag, setTag] = useState<(typeof LOOKBOOK_TAGS)[number]>("全部");
  const list = useMemo(() => {
    if (tag === "全部") return LOOKBOOK_PROMOS;
    if (tag === "美学") return LOOKBOOK_PROMOS.filter((p) => p.kind === "beauty");
    if (tag === "硬件") return LOOKBOOK_PROMOS.filter((p) => p.kind === "hardware");
    return LOOKBOOK_PROMOS.filter((p) => p.tag === tag);
  }, [tag]);

  return (
    <div className={`promo-block${compact ? " is-compact" : ""}`}>
      <div className="promo-block-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p className="muted" style={{ margin: "0.25rem 0 0" }}>{subtitle}</p>}
        </div>
        <span className="muted">{list.length} 条</span>
      </div>

      <div className="template-strip" style={{ marginBottom: "0.9rem" }}>
        {LOOKBOOK_TAGS.map((t) => (
          <button
            key={t}
            type="button"
            className={`template-chip${tag === t ? " active" : ""}`}
            onClick={() => setTag(t)}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="promo-grid">
        {list.map((p) => (
          <button
            key={p.id}
            type="button"
            className="promo-card"
            onClick={() => onPick?.(p)}
            title={onPick ? "点击后新建项目并写入 Brief" : p.title}
          >
            <img src={p.image} alt={p.title} loading="lazy" />
            <div className="promo-card-body">
              <span className="promo-card-tag">{p.tag}</span>
              <p className="promo-card-title">{p.title}</p>
              <p className="promo-card-brand">{p.brand}</p>
              {!compact && <p className="promo-card-desc">{p.description}</p>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
