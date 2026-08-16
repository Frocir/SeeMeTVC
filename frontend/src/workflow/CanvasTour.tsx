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
    title: "先认三个区域",
    body: "左：TVC Agent（默认 Auto，齐了就干）。中：无限画布，节点是真工作流。右：检查器，改提示词和参考图。切到 Plan 才有方案卡和环节卡。",
    place: "center",
  },
  {
    id: "agent",
    title: "左边这位是片子主理人",
    body: "Skill 默认 seedance-tvc。先出方案卡（Brief → 分镜 → 搭图），你点「开始」再搭画布。出片也是点「开始出片」后直接跑，不再单独确认扣费。",
    target: "agent-tab",
    place: "right",
  },
  {
    id: "palette",
    title: "也可以自己加步骤",
    body: "切到「工具」：点一项就会出现在画布上。上面是素材，中间是生成，下面是剪辑。Agent 搭完可用顶栏「一键排版」。",
    target: "palette",
    place: "right",
  },
  {
    id: "canvas",
    title: "中间是无限画布",
    body: "从左侧圆点拖到右侧圆点。文字连文字，图片连图片。常见链：文生图 → 图生视频 → 拼接。",
    target: "canvas",
    place: "bottom",
  },
  {
    id: "inspector",
    title: "右边改这一步",
    body: "点中节点，改提示词、上传参考图（会自动压缩）。Lite / 2.5 的参考图槽位不同。素材页签里的生成历史可以丢回画布。",
    target: "inspector",
    place: "left",
  },
  {
    id: "run",
    title: "整条片子怎么跑",
    body: "跟 Agent 说话让它 run_*，或点顶栏「开始生成」按连线从头跑到尾。积分按实际生成扣，不再单独弹确认卡。",
    target: "run",
    place: "bottom",
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
