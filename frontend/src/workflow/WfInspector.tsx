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
              <label>
                场景数量（整理草案用）
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={d.scene_count ?? 3}
                  onChange={(e) => onChange({ scene_count: Number(e.target.value) })}
                />
              </label>
            )}
          </>
        )}

        {nt === "ImageAsset" && (
          <>
            <ReferenceImageField
              value={d.image_url || ""}
              onChange={(url) => onChange({ image_url: url, stale: false })}
              label="图片"
              hint="本地上传或粘贴 URL"
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
            <label>
              妆前描述
              <input
                value={d.before_prompt || ""}
                onChange={(e) => onChange({ before_prompt: e.target.value })}
              />
            </label>
            <SnippetRow bucket="before" onPick={(t) => onChange({ before_prompt: t })} />
            <label>
              妆后描述
              <input
                value={d.after_prompt || ""}
                onChange={(e) => onChange({ after_prompt: e.target.value })}
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
            hint="粘贴 URL；也可由上游写入"
          />
        )}

        {nt === "ImageToVideo" && (
          <>
            <label>
              模型
              <select
                value={d.model_id || modelId}
                onChange={(e) => onChange({ model_id: e.target.value })}
              >
                {models.map((m) => (
                  <option key={m.model_id} value={m.model_id}>
                    {m.model_id} · {m.cost_per_second}/s
                  </option>
                ))}
              </select>
            </label>
            <label>
              时长（秒）
              <input
                type="number"
                min={2}
                max={30}
                value={d.duration_seconds ?? 5}
                onChange={(e) => onChange({ duration_seconds: Number(e.target.value) })}
              />
            </label>
            <label>
              本节点镜头数
              <input
                type="number"
                min={1}
                max={5}
                value={d.max_shots ?? 1}
                onChange={(e) => onChange({ max_shots: Number(e.target.value) })}
              />
            </label>
            <p className="wf-field-hint">默认 1：一段成片只占本节点。需要多镜请再拖几个「图生视频」节点，不要堆在一个节点里。</p>
            <ReferenceImageField
              value={d.image_url || ""}
              onChange={(url) => onChange({ image_url: url })}
              label="参考图（可被上游覆盖）"
              hint="槽位 image 优先"
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
              />
            </label>
          </>
        )}

        {nt === "VideoMux" && (
          <label>
            画幅
            <select value={d.aspect || "16:9"} onChange={(e) => onChange({ aspect: e.target.value })}>
              <option value="16:9">16:9</option>
              <option value="9:16">9:16</option>
            </select>
          </label>
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
