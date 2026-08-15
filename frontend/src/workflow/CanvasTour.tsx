import { useEffect, useLayoutEffect, useState } from "react";

const STORAGE_KEY = "seemetvc.canvas-guide.v1";

export type GuideStepId = "welcome" | "palette" | "canvas" | "inspector" | "run" | "agent";

export type GuideStep = {
  id: GuideStepId;
  title: string;
  body: string;
  target?: string;
  place?: "center" | "right" | "left" | "bottom";
};

export const GUIDE_STEPS: GuideStep[] = [
  {
    id: "welcome",
    title: "三步就能出片",
    body: "左边加点步骤，中间把它们连起来，点开步骤后在右边改文案或上传图。连好后点「开始生成」。",
    place: "center",
  },
  {
    id: "palette",
    title: "从这里加步骤",
    body: "点一项就会出现在画布上。上面是素材，中间是生成，下面是剪辑。",
    target: "palette",
    place: "right",
  },
  {
    id: "canvas",
    title: "把步骤连起来",
    body: "从左侧的圆点拖到右侧的圆点。文字连文字，图片连图片，对不上就连不上。",
    target: "canvas",
    place: "bottom",
  },
  {
    id: "inspector",
    title: "点步骤改内容",
    body: "选中后，右边可以改文案、上传图、选时长。只想跑当前这一步，用「生成这一步」。",
    target: "inspector",
    place: "left",
  },
  {
    id: "run",
    title: "生成整条片子",
    body: "「开始生成」会按连线从头跑到尾。要扣费时会先问你，确认前不会开始。",
    target: "run",
    place: "bottom",
  },
  {
    id: "agent",
    title: "左边这位是片子主理人",
    body: "像找一支真人团队：先跟他聊方案，谈妥了再让他去画布上搭。要扣费仍会先问你。",
    target: "agent-tab",
    place: "right",
  },
];

export function shouldStartCanvasGuide(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "1";
  } catch {
    return false;
  }
}

export function markCanvasGuideDone(): void {
  try {
    localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    /* ignore */
  }
}

type Props = {
  open: boolean;
  onClose: () => void;
  onStep: (id: GuideStepId) => void;
};

type Box = { top: number; left: number; width: number; height: number };

function readTarget(selector: string | undefined): Box | null {
  if (!selector) return null;
  const el = document.querySelector(`[data-tour="${selector}"]`);
  if (!(el instanceof HTMLElement)) return null;
  const r = el.getBoundingClientRect();
  if (r.width < 2 && r.height < 2) return null;
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n));
}

export default function CanvasTour({ open, onClose, onStep }: Props) {
  const [index, setIndex] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const step = GUIDE_STEPS[index];

  useEffect(() => {
    if (!open) {
      setIndex(0);
      return;
    }
    setIndex(0);
  }, [open]);

  useEffect(() => {
    if (!open || !step) return;
    onStep(step.id);
  }, [open, step, onStep]);

  useLayoutEffect(() => {
    if (!open || !step) return;
    let alive = true;
    const measure = () => {
      if (!alive) return;
      setBox(readTarget(step.target));
    };
    measure();
    const t = window.setTimeout(measure, 80);
    const t2 = window.setTimeout(measure, 220);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      alive = false;
      window.clearTimeout(t);
      window.clearTimeout(t2);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, step]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" || e.key === "Enter") {
        setIndex((i) => {
          if (i + 1 >= GUIDE_STEPS.length) {
            onClose();
            return i;
          }
          return i + 1;
        });
      }
      if (e.key === "ArrowLeft") setIndex((i) => Math.max(0, i - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !step) return null;

  function go(delta: number) {
    const next = index + delta;
    if (next < 0) return;
    if (next >= GUIDE_STEPS.length) {
      onClose();
      return;
    }
    setIndex(next);
  }

  const pad = 8;
  const highlight = box
    ? {
        top: box.top - pad,
        left: box.left - pad,
        width: box.width + pad * 2,
        height: box.height + pad * 2,
      }
    : null;

  const cardW = 320;
  let cardTop = window.innerHeight / 2 - 90;
  let cardLeft = window.innerWidth / 2 - cardW / 2;
  if (highlight && step.place === "right") {
    cardLeft = highlight.left + highlight.width + 16;
    cardTop = highlight.top;
  } else if (highlight && step.place === "left") {
    cardLeft = highlight.left - cardW - 16;
    cardTop = highlight.top;
  } else if (highlight && step.place === "bottom") {
    cardLeft = highlight.left + highlight.width / 2 - cardW / 2;
    cardTop = highlight.top + highlight.height + 16;
  }
  cardLeft = clamp(cardLeft, 12, window.innerWidth - cardW - 12);
  cardTop = clamp(cardTop, 12, window.innerHeight - 220);

  return (
    <div className="cv-tour" role="dialog" aria-modal="true" aria-labelledby="cv-tour-title">
      <div className={`cv-tour-dim${highlight ? " is-cutout" : ""}`} onClick={onClose} />
      {highlight && (
        <div
          className="cv-tour-spot"
          style={{
            top: highlight.top,
            left: highlight.left,
            width: highlight.width,
            height: highlight.height,
          }}
        />
      )}
      <div className="cv-tour-card" style={{ top: cardTop, left: cardLeft, width: cardW }}>
        <p className="cv-tour-step">
          {index + 1} / {GUIDE_STEPS.length}
        </p>
        <h2 id="cv-tour-title">{step.title}</h2>
        <p>{step.body}</p>
        <div className="cv-tour-actions">
          <button type="button" className="ghost" onClick={onClose}>
            跳过
          </button>
          <div className="cv-tour-nav">
            {index > 0 && (
              <button type="button" className="ghost" onClick={() => go(-1)}>
                上一步
              </button>
            )}
            <button type="button" className="primary" onClick={() => go(1)}>
              {index === GUIDE_STEPS.length - 1 ? "开始用" : "下一步"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
