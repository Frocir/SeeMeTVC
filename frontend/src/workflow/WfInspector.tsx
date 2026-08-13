import ReferenceImageField from "../components/ReferenceImageField";
import type { ModelOption } from "../api";
import { PROMPT_SNIPPETS, type PromptBucket } from "./prompts";
import { normalizeNodeType, type WfData } from "./types";

type Props = {
  data: WfData | null;
  models: ModelOption[];
  modelId: string;
  onChange: (patch: Partial<WfData>) => void;
  onDelete: () => void;
  onGenerate?: () => void;
  canGenerate?: boolean;
};

function SnippetRow({
  bucket,
  onPick,
}: {
  bucket: PromptBucket;
  onPick: (text: string) => void;
}) {
  const items = PROMPT_SNIPPETS[bucket];
  return (
    <div className="wf-snippets">
      {items.map((s) => (
        <button key={s.id} type="button" className="wf-chip" onClick={() => onPick(s.text)}>
          {s.label}
        </button>
      ))}
    </div>
  );
}

function appendText(current: string | undefined, text: string): string {
  const cur = (current || "").trim();
  if (!cur) return text;
  if (cur.includes(text)) return cur;
  return `${cur}，${text}`;
}

export default function WfInspector({
  data,
  models,
  modelId,
  onChange,
  onDelete,
  onGenerate,
  canGenerate,
}: Props) {
  if (!data) {
    return (
      <aside className="wf-inspector">
        <p className="muted">选中节点可改参数；节点上可直接改名称。双击媒体可全屏。</p>
      </aside>
    );
  }

  const d = data;
  const nt = normalizeNodeType(d.nodeType);

  return (
    <aside className="wf-inspector">
      <div className="wf-fields">
        <label>
          名称
          <input value={d.label} onChange={(e) => onChange({ label: e.target.value })} />
        </label>

        {d.stale && <p className="wf-stale-hint">上游已变更，当前结果已过期</p>}
        {d.simulated && <p className="wf-sim-hint">此结果为超管模拟填入</p>}

        {nt === "TextAsset" && (
          <>
            <label>
              文本角色
              <select
                value={d.textRole || "brief"}
                onChange={(e) =>
                  onChange({ textRole: e.target.value as WfData["textRole"] })
                }
              >
                <option value="brief">Brief</option>
                <option value="script">剧本</option>
                <option value="prompt">提示词</option>
                <option value="notes">备注</option>
              </select>
            </label>
            {(d.textRole || "brief") === "brief" && (
              <>
                <label>
                  品牌
                  <input value={d.brand || ""} onChange={(e) => onChange({ brand: e.target.value })} />
                </label>
                <label>
                  卖点
                  <input
                    value={d.selling_points || ""}
                    onChange={(e) => onChange({ selling_points: e.target.value })}
                  />
                </label>
                <label>
                  Slogan
                  <input
                    value={d.slogan || ""}
                    onChange={(e) => onChange({ slogan: e.target.value })}
                  />
                </label>
                <SnippetRow bucket="slogan" onPick={(t) => onChange({ slogan: t })} />
              </>
            )}
            <label>
              正文 / 提示
              <textarea
                rows={4}
                value={d.prompt || d.text || ""}
                onChange={(e) => onChange({ prompt: e.target.value, text: e.target.value })}
              />
            </label>
            <SnippetRow
              bucket="brief"
              onPick={(t) => onChange({ prompt: appendText(d.prompt, t), text: appendText(d.text, t) })}
            />
            {(d.textRole === "script" || d.scene_count != null) && (
              <>
                <label>
                  场景数量（整理草案用）
                  <input
                    type="number"
                    min={1}
                    max={5}
                    step={1}
                    value={d.scene_count ?? 3}
                    onChange={(e) => onChange({ scene_count: Number(e.target.value) })}
                    onBlur={(e) => {
                      const n = Math.max(1, Math.min(5, Number(e.target.value) || 3));
                      onChange({ scene_count: n });
                    }}
                  />
                </label>
                <p className="wf-field-hint">
                  有效范围 <strong>1–5</strong>。仅用于本地拼装分镜草案文案，不会单独调 AI。
                </p>
              </>
            )}
          </>
        )}

        {nt === "ImageAsset" && (
          <>
            <ReferenceImageField
              value={d.image_url || ""}
              onChange={(url) => onChange({ image_url: url, stale: false })}
              label="图片"
              hint="本地上传或粘贴 URL；下游图生视频优先用此图"
            />
            <label>
              妆容强度 {Math.round((d.intensity ?? 0.7) * 100)}%
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={d.intensity ?? 0.7}
                onChange={(e) => onChange({ intensity: Number(e.target.value) })}
              />
            </label>
            <p className="wf-field-hint">
              会写入下游提示词里的「妆容强度」描述，<strong>不是</strong>真实修图/换妆模型。
            </p>
            <label>
              妆前描述
              <input
                value={d.before_prompt || ""}
                onChange={(e) => onChange({ before_prompt: e.target.value })}
                placeholder="素颜 / 妆前状态"
              />
            </label>
            <SnippetRow bucket="before" onPick={(t) => onChange({ before_prompt: t })} />
            <label>
              妆后描述
              <input
                value={d.after_prompt || ""}
                onChange={(e) => onChange({ after_prompt: e.target.value })}
                placeholder="妆后气色"
              />
            </label>
            <SnippetRow bucket="after" onPick={(t) => onChange({ after_prompt: t })} />
          </>
        )}

        {nt === "VideoAsset" && (
          <ReferenceImageField
            value={d.result_url || d.clip_url || d.preview_url || ""}
            onChange={(url) =>
              onChange({
                result_url: url,
                clip_url: url,
                preview_url: url,
                stale: false,
              })
            }
            label="视频地址"
            hint="粘贴可播的 mp4 URL；也可由上游节点写入"
          />
        )}

        {nt === "ImageToVideo" && (
          <>
            {(() => {
              const m = models.find((x) => x.model_id === (d.model_id || modelId));
              const dMin = m?.duration_min ?? 2;
              const dMax = m?.duration_max ?? 30;
              const clampDur = (raw: number) =>
                Math.max(dMin, Math.min(dMax, Number.isFinite(raw) ? raw : dMin));
              return (
                <>
                  <label>
                    模型
                    <select
                      value={d.model_id || modelId}
                      onChange={(e) => {
                        const mid = e.target.value;
                        const nextModel = models.find((x) => x.model_id === mid);
                        const next: Partial<WfData> = { model_id: mid };
                        if (nextModel?.duration_min != null && nextModel?.duration_max != null) {
                          const cur = d.duration_seconds ?? 5;
                          next.duration_seconds = Math.max(
                            nextModel.duration_min,
                            Math.min(nextModel.duration_max, cur),
                          );
                        }
                        onChange(next);
                      }}
                    >
                      {models.map((opt) => (
                        <option key={opt.model_id} value={opt.model_id}>
                          {opt.label || opt.model_id}
                          {opt.supports_audio ? " · 有声" : " · 无声"}
                          {" · "}
                          {opt.cost_per_second}/s
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    镜头提示词
                    <textarea
                      rows={3}
                      value={d.prompt || ""}
                      onChange={(e) => onChange({ prompt: e.target.value })}
                      placeholder="描述镜头动作、光影、产品质感…"
                    />
                  </label>
                  <p className="wf-field-hint">
                    必填（或从上游 <strong>prompt</strong> 槽接入）。本栏有内容时优先用本栏；为空则用上游。都空会报「缺少有效提示词」。
                  </p>
                  <label>
                    时长（秒）
                    <input
                      type="number"
                      min={dMin}
                      max={dMax}
                      step={1}
                      value={d.duration_seconds ?? Math.min(5, dMax)}
                      onChange={(e) => onChange({ duration_seconds: Number(e.target.value) })}
                      onBlur={(e) => {
                        const next = clampDur(Number(e.target.value));
                        if (next !== Number(e.target.value) || next !== (d.duration_seconds ?? 5)) {
                          onChange({ duration_seconds: next });
                        }
                      }}
                    />
                  </label>
                  <p className="wf-field-hint">
                    当前模型有效时长 <strong>{dMin}–{dMax} 秒</strong>
                    {m?.model_id === "seedance-2.5"
                      ? "（火山方舟 Seedance 2.x 最短约 4 秒；填更短会按下限生成并计费）。"
                      : m?.model_id === "seedance-lite"
                        ? "（火山方舟 Seedance Lite：约 2–12 秒；超出范围会自动夹紧）。"
                        : m?.provider === "mock"
                          ? "（本地模拟版样片时长）。"
                          : "（超出范围提交时会自动夹紧）。"}
                    {" "}一键跑使用本节点此时长。
                  </p>
                  {m && (
                    <p className="wf-field-hint">
                      {m.provider === "mock"
                        ? "本地seedance模拟版（Seedance LocalSimulate）：本机样片，不是真实 Seedance。"
                        : m.model_id === "seedance-2.5"
                          ? "火山方舟 Seedance 2.x：有参考图走图生，否则文生；默认同步音频。"
                          : m.model_id === "seedance-lite"
                            ? "火山方舟 Seedance Lite：有参考图走图生，否则文生；无原生音频。"
                            : null}
                    </p>
                  )}
                </>
              );
            })()}
            <label>
              本节点镜头数
              <input
                type="number"
                min={1}
                max={5}
                step={1}
                value={d.max_shots ?? 1}
                onChange={(e) => onChange({ max_shots: Number(e.target.value) })}
                onBlur={(e) => {
                  const n = Math.max(1, Math.min(5, Number(e.target.value) || 1));
                  onChange({ max_shots: n });
                }}
              />
            </label>
            <p className="wf-field-hint">
              有效 <strong>1–5</strong>。默认 1：一镜一段。大于 1 且上游带多段 scenes 时会<strong>连续生成多段并多次扣费</strong>；一般请再拖多个「图生视频」节点，而不是加大此数。
            </p>
            <ReferenceImageField
              value={d.image_url || ""}
              onChange={(url) => onChange({ image_url: url })}
              label="参考图（可被上游覆盖）"
              hint="有图 → 图生视频；无图 → 文生视频。槽位 image 优先于本栏。"
            />
          </>
        )}

        {nt === "VideoTrim" && (
          <>
            <label>
              起始秒
              <input
                type="number"
                min={0}
                step={0.1}
                value={d.trim_start ?? 0}
                onChange={(e) => onChange({ trim_start: Number(e.target.value) })}
                onBlur={(e) => {
                  const start = Math.max(0, Number(e.target.value) || 0);
                  const end = d.trim_end ?? 4;
                  onChange({
                    trim_start: start,
                    ...(end <= start ? { trim_end: start + 0.1 } : {}),
                  });
                }}
              />
            </label>
            <label>
              结束秒
              <input
                type="number"
                min={0.1}
                step={0.1}
                value={d.trim_end ?? 4}
                onChange={(e) => onChange({ trim_end: Number(e.target.value) })}
                onBlur={(e) => {
                  const start = d.trim_start ?? 0;
                  let end = Number(e.target.value);
                  if (!Number.isFinite(end) || end <= start) end = start + 0.1;
                  onChange({ trim_end: end });
                }}
              />
            </label>
            <p className="wf-field-hint">
              必须 <strong>结束秒 &gt; 起始秒</strong>。按上游成片时间轴裁切；若结束秒超过片长，ffmpeg 可能失败或裁出空结果。模板默认 0–4 秒，请按实际上游时长调整。
            </p>
          </>
        )}

        {nt === "VideoMux" && (
          <>
            <label>
              画幅标记
              <select value={d.aspect || "16:9"} onChange={(e) => onChange({ aspect: e.target.value })}>
                <option value="16:9">16:9</option>
                <option value="9:16">9:16</option>
              </select>
            </label>
            <p className="wf-field-hint">
              当前拼接<strong>不会按此重编码改画幅</strong>，只写入结果元数据；成片比例取决于上游片段本身。
            </p>
          </>
        )}

        {onGenerate && (
          <button type="button" className="primary solid" disabled={!canGenerate} onClick={onGenerate}>
            生成此节点
          </button>
        )}

        {d.runStatus && (
          <div className="wf-run-out">
            <p className="eyebrow">最近执行</p>
            <p>
              状态 <strong>{d.runStatus}</strong>
            </p>
            {d.runError && <p className="error">{d.runError}</p>}
          </div>
        )}

        <button type="button" className="ghost danger" onClick={onDelete}>
          删除节点
        </button>
      </div>
    </aside>
  );
}
