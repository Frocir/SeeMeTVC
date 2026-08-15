import { useCallback, useRef, useState } from "react";
import type { WfData } from "../types";

type Props = {
  data: WfData;
  onPatch?: (patch: Partial<WfData>) => void;
  onOpenFullscreen?: (url: string, kind: "image" | "video" | "audio") => void;
};

function pickUrl(data: WfData, which: "before" | "after"): string {
  return String(which === "before" ? data.before_url || "" : data.after_url || "").trim();
}

function selectedUrl(data: WfData): string {
  const sel = data.selected === "before" ? "before" : "after";
  return pickUrl(data, sel) || pickUrl(data, sel === "before" ? "after" : "before");
}

export default function ImageCompareView({ data, onPatch, onOpenFullscreen }: Props) {
  const before = pickUrl(data, "before");
  const after = pickUrl(data, "after");
  const selected = data.selected === "before" ? "before" : "after";
  const mode = data.compare_mode === "side_by_side" ? "side_by_side" : "slider";
  const [split, setSplit] = useState(50);
  const trackRef = useRef<HTMLDivElement>(null);

  const choose = useCallback(
    (which: "before" | "after") => {
      const url = pickUrl(data, which);
      onPatch?.({ selected: which, url: url || undefined, image_url: url || undefined });
    },
    [data, onPatch],
  );

  const moveSplit = useCallback((clientX: number) => {
    const el = trackRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const next = ((clientX - rect.left) / Math.max(rect.width, 1)) * 100;
    setSplit(Math.max(4, Math.min(96, next)));
  }, []);

  if (!before && !after) {
    return (
      <div className="cv-compare-empty">
        <span>连接 A / B 两张图后对比</span>
      </div>
    );
  }

  if (mode === "side_by_side") {
    return (
      <div className="cv-compare side nodrag nopan">
        {(["before", "after"] as const).map((which) => {
          const url = which === "before" ? before : after;
          return (
            <button
              key={which}
              type="button"
              className={`cv-compare-pane ${selected === which ? "is-on" : ""}`}
              onClick={() => choose(which)}
              onDoubleClick={(e) => {
                e.stopPropagation();
                if (url) onOpenFullscreen?.(url, "image");
              }}
            >
              {url ? <img src={url} alt="" /> : <span className="cv-compare-miss">{which === "before" ? "缺 A 图" : "缺 B 图"}</span>}
              <em>{which === "before" ? "A" : "B"}</em>
            </button>
          );
        })}
      </div>
    );
  }

  if (!before || !after) {
    const only = before || after;
    const which = before ? "before" : "after";
    return (
      <div className="cv-compare slider nodrag nopan">
        <div
          className="cv-compare-track"
          onDoubleClick={(e) => {
            e.stopPropagation();
            if (only) onOpenFullscreen?.(only, "image");
          }}
        >
          <img className="cv-compare-base" src={only} alt="" />
          <span className="cv-compare-miss is-overlay">{which === "before" ? "缺 B 图" : "缺 A 图"}</span>
        </div>
        <div className="cv-compare-pick">
          <button type="button" className={selected === "before" ? "is-on" : ""} onClick={() => choose("before")} disabled={!before}>
            A
          </button>
          <button type="button" className={selected === "after" ? "is-on" : ""} onClick={() => choose("after")} disabled={!after}>
            B
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="cv-compare slider nodrag nopan">
      <div
        ref={trackRef}
        className="cv-compare-track"
        onPointerDown={(e) => {
          (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
          moveSplit(e.clientX);
        }}
        onPointerMove={(e) => {
          if (e.buttons) moveSplit(e.clientX);
        }}
        onDoubleClick={(e) => {
          e.stopPropagation();
          const url = selectedUrl(data);
          if (url) onOpenFullscreen?.(url, "image");
        }}
      >
        <img className="cv-compare-base" src={after} alt="" />
        <div className="cv-compare-clip" style={{ width: `${split}%` }}>
          <img src={before} alt="" style={{ width: `${(100 / Math.max(split, 1)) * 100}%` }} />
        </div>
        <div className="cv-compare-bar" style={{ left: `${split}%` }}>
          <span />
        </div>
      </div>
      <div className="cv-compare-pick">
        <button type="button" className={selected === "before" ? "is-on" : ""} onClick={() => choose("before")} disabled={!before}>
          A
        </button>
        <button type="button" className={selected === "after" ? "is-on" : ""} onClick={() => choose("after")} disabled={!after}>
          B
        </button>
      </div>
    </div>
  );
}
