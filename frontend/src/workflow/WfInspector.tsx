import { useRef, useState } from "react";
import ReferenceImageField from "../components/ReferenceImageField";
import { uploadAudio, uploadVideo, type ModelCapabilities, type ModelOption } from "../api";
import { PROMPT_SNIPPETS, type PromptBucket } from "./prompts";
import { LLM_SYSTEM, TTS_VOICES, shotSystem } from "./templates";
import { isLlmNodeType, normalizeNodeType, type WfData } from "./types";

type Props = {
  data: WfData | null;
  models: ModelOption[];
  llmModels?: ModelOption[];
  ttsModels?: ModelOption[];
  imageModels?: ModelOption[];
  asrModels?: ModelOption[];
  modelId: string;
  onChange: (patch: Partial<WfData>) => void;
  onDelete: () => void;
  onGenerate?: () => void;
  canGenerate?: boolean;
  onExpandScenes?: (mode: "silent" | "with_image" | "with_tts" | "full_tvc") => void;
  canExpandScenes?: boolean;
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

async function copyText(value: string): Promise<void> {
  const text = (value || "").trim();
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* ignore */
  }
}

function capsOf(models: ModelOption[], modelId?: string): ModelCapabilities {
  const id = (modelId || "").trim();
  const hit = models.find((m) => m.model_id === id) || models[0];
  return hit?.capabilities || {};
}

function AudioUpload({ value, onChange }: { value: string; onChange: (url: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const res = await uploadAudio(file);
      onChange(res.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <label>
        音频地址
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="粘贴地址，或点下面上传" />
      </label>
      <button type="button" className="ghost" disabled={busy} onClick={() => ref.current?.click()}>
        {busy ? "上传中…" : "上传音频"}
      </button>
      <input
        ref={ref}
        type="file"
        hidden
        accept="audio/mpeg,audio/wav,audio/mp4,audio/aac,.mp3,.wav,.m4a,.aac"
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          void onFile(f);
        }}
      />
      {value && <audio src={value} controls style={{ width: "100%", marginTop: "0.4rem" }} />}
      {error && <p className="error">{error}</p>}
      <p className="wf-field-hint">支持 mp3 / wav / m4a。模板里的演示配乐可以换成自己的。</p>
    </>
  );
}

function VideoUpload({ value, onChange }: { value: string; onChange: (url: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const res = await uploadVideo(file);
      onChange(res.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = "";
    }
  }
  return (
    <>
      <label>
        视频地址
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="粘贴地址，或点下面上传 mp4" />
      </label>
      <button type="button" className="ghost" disabled={busy} onClick={() => ref.current?.click()}>
        {busy ? "上传中…" : "上传视频"}
      </button>
      <input
        ref={ref}
        type="file"
        hidden
        accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov"
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      {value && <video src={value} controls style={{ width: "100%", marginTop: "0.4rem" }} />}
      {error && <p className="error">{error}</p>}
      <p className="wf-field-hint">支持 mp4 / webm / mov。可接到拆参考片、裁视频、拆声音。</p>
    </>
  );
}

export default function WfInspector({
  data,
  models,
  llmModels = [],
  ttsModels = [],
  imageModels = [],
  asrModels = [],
  modelId,
  onChange,
  onDelete,
  onGenerate,
  canGenerate,
  onExpandScenes,
  canExpandScenes,
}: Props) {
  if (!data) {
    return (
      <aside className="wf-inspector">
        <p className="muted">点画布上的步骤，就能改文案、上传图或选时长。双击图片/视频可放大。</p>
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

        {d.stale && <p className="wf-stale-hint">前面的步骤改过了，当前结果已经过期</p>}

        {nt === "TextAsset" && (
          <>
            <label>
              这份文案是
              <select
                value={d.textRole || "brief"}
                onChange={(e) =>
                  onChange({ textRole: e.target.value as WfData["textRole"] })
                }
              >
                <option value="brief">品牌简介</option>
                <option value="prompt">画面描述</option>
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
                  口号
                  <input
                    value={d.slogan || ""}
                    onChange={(e) => onChange({ slogan: e.target.value })}
                  />
                </label>
                <SnippetRow bucket="slogan" onPick={(t) => onChange({ slogan: t })} />
              </>
            )}
            <label>
              正文
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
          </>
        )}

        {nt === "ImageAsset" && (
          <>
            <ReferenceImageField
              value={d.image_url || ""}
              onChange={(url) => onChange({ image_url: url, stale: false })}
              label="图片"
              hint="上传或粘贴图片地址。可接到出图或出视频。"
            />
          </>
        )}

        {nt === "VideoAsset" && (
          <VideoUpload
            value={d.result_url || d.clip_url || d.preview_url || ""}
            onChange={(url) =>
              onChange({
                result_url: url,
                clip_url: url,
                preview_url: url,
                stale: false,
              })
            }
          />
        )}

        {nt === "VideoReversePrompt" && (
          <>
            <VideoUpload
              value={d.result_url || d.clip_url || d.preview_url || d.reference_video_url || ""}
              onChange={(url) =>
                onChange({
                  result_url: url,
                  clip_url: url,
                  preview_url: url,
                  reference_video_url: url,
                  stale: false,
                })
              }
            />
            <label>
              你想怎么用这条参考片
              <textarea
                rows={4}
                value={d.prompt || d.text || ""}
                onChange={(e) => onChange({ prompt: e.target.value, text: e.target.value })}
                placeholder="例如：参考这个视频的运镜和光线，改成某品牌精华液广告"
              />
            </label>
            <label>
              抽帧策略
              <select
                value={d.frame_strategy || "scene_detect"}
                onChange={(e) => onChange({ frame_strategy: e.target.value as WfData["frame_strategy"] })}
              >
                <option value="scene_detect">智能切镜</option>
                <option value="fixed">固定间隔</option>
              </select>
            </label>
            <label>
              固定抽几张
              <input
                type="number"
                min={1}
                max={6}
                step={1}
                value={d.frame_count ?? 3}
                onChange={(e) => onChange({ frame_count: Number(e.target.value) })}
              />
            </label>
            <label>
              最多拆几镜
              <input
                type="number"
                min={1}
                max={12}
                step={1}
                value={d.max_scenes ?? 6}
                onChange={(e) => onChange({ max_scenes: Number(e.target.value) })}
              />
            </label>
            <label>
              镜头切换灵敏度
              <input
                type="number"
                min={0.02}
                max={0.95}
                step={0.01}
                value={d.scene_threshold ?? 0.28}
                onChange={(e) => onChange({ scene_threshold: Number(e.target.value) })}
              />
            </label>
            <label>
              每秒抽几帧
              <input
                type="number"
                min={0.25}
                max={6}
                step={0.25}
                value={d.sample_fps ?? 2}
                onChange={(e) => onChange({ sample_fps: Number(e.target.value) })}
              />
            </label>
            <label>
              提示词风格
              <select
                value={d.prompt_style || "seedance"}
                onChange={(e) => onChange({ prompt_style: e.target.value as WfData["prompt_style"] })}
              >
                <option value="seedance">Seedance 中文</option>
                <option value="jimeng">即梦中文</option>
                <option value="midjourney">Midjourney 英文</option>
                <option value="all">全部</option>
              </select>
            </label>
            {Array.isArray(d.frames) && d.frames.length > 0 && (
              <div className="wf-field-hint">
                已抽取关键帧：{d.frames.length} 张；分镜：{Array.isArray(d.scenes) ? d.scenes.length : 0} 个。
              </div>
            )}
            <div className="wf-expand-actions">
              <button
                type="button"
                className="ghost"
                disabled={!canExpandScenes}
                onClick={() => onExpandScenes?.("with_image")}
              >
                按分镜摆到画布
              </button>
              <button
                type="button"
                className="ghost"
                disabled={!canExpandScenes}
                onClick={() => onExpandScenes?.("silent")}
              >
                只要视频镜头
              </button>
            </div>
            <p className="wf-field-hint">跑完会得到分镜、画面描述和关键帧。点上面的按钮可以自动摆到画布上。</p>
          </>
        )}

        {nt === "ImageToVideo" && (
          <>
            {(() => {
              const m = models.find((x) => x.model_id === (d.model_id || modelId));
              const caps = capsOf(models, d.model_id || modelId);
              const dMin = caps.duration_min ?? m?.duration_min ?? 2;
              const dMax = caps.duration_max ?? m?.duration_max ?? 30;
              const clampDur = (raw: number) =>
                Math.max(dMin, Math.min(dMax, Number.isFinite(raw) ? raw : dMin));
              const lastOk = Boolean(caps.supports_first_last_frame);
              const styleOk = Boolean(caps.supports_style_reference);
              const charOk = Boolean(caps.supports_character_reference);
              const productOk = Boolean(caps.supports_product_reference);
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
                    写这一镜要拍什么。左边接上文字也可以；这里填了就优先用这里的。
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
                        : "（超出范围提交时会自动夹紧）。"}
                    {" "}点「开始生成」时用这里的时长。
                  </p>
                  {m && (
                    <p className="wf-field-hint">
                      {m.model_id === "seedance-2.5"
                        ? "火山方舟 Seedance 2.x：有参考图走图生，否则文生；默认同步音频。支持首尾帧。"
                        : m.model_id === "seedance-lite"
                          ? "火山方舟 Seedance Lite：有参考图走图生，否则文生；无原生音频。不支持首尾帧。"
                          : null}
                    </p>
                  )}
                  <ReferenceImageField
                    value={d.first_image_url || d.image_url || ""}
                    onChange={(url) => onChange({ image_url: url, first_image_url: url })}
                    label="首帧图"
                    hint="有图就按图生成；没图就按文字生成。左边接上的图会优先使用。"
                  />
                  <ReferenceImageField
                    value={d.last_image_url || ""}
                    onChange={(url) => onChange({ last_image_url: url })}
                    label="尾帧"
                    hint="不是所有模型都支持尾帧。"
                    disabled={!lastOk}
                    disabledHint="当前模型不支持首尾帧输入，请更换模型或移除尾帧。"
                  />
                  <ReferenceImageField
                    value={d.style_image_url || ""}
                    onChange={(url) => onChange({ style_image_url: url })}
                    label="风格参考图"
                    hint="可选。"
                    disabled={!styleOk}
                    disabledHint="当前模型不支持风格参考图。"
                  />
                  <ReferenceImageField
                    value={d.character_image_url || ""}
                    onChange={(url) => onChange({ character_image_url: url })}
                    label="角色参考图"
                    hint="可选。"
                    disabled={!charOk}
                    disabledHint="当前模型不支持角色参考图。"
                  />
                  <ReferenceImageField
                    value={d.product_image_url || ""}
                    onChange={(url) => onChange({ product_image_url: url })}
                    label="产品参考图"
                    hint="有产品图时建议放这里。"
                    disabled={!productOk}
                    disabledHint="当前模型不支持产品参考图。"
                  />
                  {(lastOk || styleOk || charOk || productOk) && (
                    <label>
                      参考强度
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={d.reference_strength ?? 0.7}
                        onChange={(e) => onChange({ reference_strength: Number(e.target.value) })}
                      />
                    </label>
                  )}
                </>
              );
            })()}
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
                  const end = d.trim_end ?? 5;
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
                value={d.trim_end ?? 5}
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
              结束秒必须大于起始秒。如果结束秒超过片子长度，这一步会失败。
            </p>
          </>
        )}

        {nt === "VideoMux" && (
          <>
            <label>
              画面比例
              <select value={d.aspect || "16:9"} onChange={(e) => onChange({ aspect: e.target.value })}>
                <option value="16:9">16:9</option>
                <option value="9:16">9:16</option>
              </select>
            </label>
            <p className="wf-field-hint">
              这里只是标记比例，不会把片子拉伸。成片比例跟接进来的片段一样。
            </p>
          </>
        )}

        {nt === "AudioAsset" && (
          <AudioUpload
            value={d.audio_url || ""}
            onChange={(url) => onChange({ audio_url: url, stale: false })}
          />
        )}

        {nt === "MixAudio" && (
          <p className="wf-field-hint">
            左边要接上视频、配乐和口播，缺一个就会失败。配乐会循环到画面长度；口播太长会被裁掉。
          </p>
        )}

        {nt === "VideoDemux" && (
          <p className="wf-field-hint">
            把有声视频拆成静音画面和音轨。片子里没有声音时这一步会失败。想去掉原声再混音，先接这一步。
          </p>
        )}

        {nt === "TextToImage" && (
          <>
            {(() => {
              const caps = capsOf(imageModels, d.model_id);
              const sizes = caps.sizes?.length ? caps.sizes : ["1024x1024"];
              const sizeOk = Boolean(caps.sizes?.length);
              const seedOk = Boolean(caps.supports_seed);
              const negOk = Boolean(caps.supports_negative_prompt);
              const strengthOk = Boolean(caps.supports_image_strength);
              const batchOk = Boolean(caps.supports_batch);
              return (
                <>
            <label>
              出图模型
              <select
                value={d.model_id || imageModels[0]?.model_id || ""}
                onChange={(e) => onChange({ model_id: e.target.value })}
              >
                {imageModels.length === 0 && <option value="">（无可用出图模型）</option>}
                {imageModels.map((opt) => (
                  <option key={opt.model_id} value={opt.model_id}>
                    {opt.label || opt.model_id}
                    {opt.cost_per_second ? ` · ${opt.cost_per_second}/张` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              画面描述
              <textarea
                rows={3}
                value={d.prompt || d.text || ""}
                onChange={(e) => onChange({ prompt: e.target.value, text: e.target.value })}
              />
            </label>
            <ReferenceImageField
              value={d.image_url || ""}
              onChange={(url) => onChange({ image_url: url })}
              label="参考图（可选）"
              hint="有参考图会尽量按图来。"
              disabled={caps.supports_image_to_image === false}
              disabledHint="当前模型不支持图生图，请移除参考图或更换模型。"
            />
            <label className={sizeOk ? "" : "wf-cap-off"}>
              尺寸
              <select
                value={d.size || sizes[0]}
                disabled={!sizeOk}
                onChange={(e) => onChange({ size: e.target.value })}
              >
                {sizes.map((sz) => (
                  <option key={sz} value={sz}>
                    {sz}
                  </option>
                ))}
              </select>
            </label>
            {!sizeOk && <p className="wf-field-hint">当前模型不支持指定尺寸。</p>}
            <label className={negOk ? "" : "wf-cap-off"}>
              不要出现的内容
              <textarea
                rows={2}
                disabled={!negOk}
                value={d.negative_prompt || ""}
                onChange={(e) => onChange({ negative_prompt: e.target.value })}
                placeholder={negOk ? "例如：不要字幕、水印、错字" : "当前模型不支持这项"}
              />
            </label>
            <label className={seedOk ? "" : "wf-cap-off"}>
              随机种子
              <input
                type="number"
                min={0}
                step={1}
                disabled={!seedOk}
                value={d.seed ?? ""}
                onChange={(e) => onChange({ seed: e.target.value === "" ? undefined : Number(e.target.value) })}
                placeholder={seedOk ? "可留空" : "当前模型不支持这项"}
              />
            </label>
            <label className={batchOk ? "" : "wf-cap-off"}>
              批量张数
              <input
                type="number"
                min={1}
                max={4}
                step={1}
                disabled={!batchOk}
                value={d.batch_size ?? 1}
                onChange={(e) => onChange({ batch_size: Number(e.target.value) })}
              />
            </label>
            <label className={strengthOk ? "" : "wf-cap-off"}>
              参考图强度
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                disabled={!strengthOk}
                value={d.image_strength ?? 0.7}
                onChange={(e) => onChange({ image_strength: Number(e.target.value) })}
              />
            </label>
            {(!seedOk || !negOk || !strengthOk) && (
              <p className="wf-field-hint">灰色项是当前模型做不到的，不会提交。</p>
            )}
            <p className="wf-field-hint">
              图像渠道按「每张图片」扣费，点开始出片或「生成这一步」后直接跑。
            </p>
                </>
              );
            })()}
          </>
        )}

        {nt === "ImageCompare" && (
          <>
            <label>
              对比模式
              <select
                value={d.compare_mode || "slider"}
                onChange={(e) => onChange({ compare_mode: e.target.value as WfData["compare_mode"] })}
              >
                <option value="slider">滑杆对比</option>
                <option value="side_by_side">左右并排</option>
              </select>
            </label>
            <label>
              输出选择
              <select
                value={d.selected || "after"}
                onChange={(e) => {
                  const selected = e.target.value as "before" | "after";
                  const url = selected === "before" ? d.before_url : d.after_url;
                  onChange({ selected, url: url || "", image_url: url || "" });
                }}
              >
                <option value="before">A（before）</option>
                <option value="after">B（after）</option>
              </select>
            </label>
            <div className="wf-compare-thumbs">
              <div>
                <p className="wf-field-hint">A</p>
                {d.before_url ? <img src={d.before_url} alt="" /> : <span className="muted">未接入</span>}
              </div>
              <div>
                <p className="wf-field-hint">B</p>
                {d.after_url ? <img src={d.after_url} alt="" /> : <span className="muted">未接入</span>}
              </div>
            </div>
            <button
              type="button"
              className="ghost"
              disabled={!d.before_url && !d.after_url}
              onClick={() => {
                const before = d.after_url || "";
                const after = d.before_url || "";
                const selected = d.selected === "before" ? "after" : "before";
                const url = selected === "before" ? before : after;
                onChange({
                  before_url: before,
                  after_url: after,
                  selected,
                  url,
                  image_url: url,
                });
              }}
            >
              交换 A / B
            </button>
            <p className="wf-field-hint">跑完后，当前选中的那张会传到后面的步骤。</p>
          </>
        )}

        {nt === "AudioTrim" && (
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
              结束秒（0 = 整段）
              <input
                type="number"
                min={0}
                step={0.1}
                value={d.trim_end ?? 0}
                onChange={(e) => onChange({ trim_end: Number(e.target.value) })}
              />
            </label>
            <p className="wf-field-hint">结束秒填 0，或比起始还小，就整段原样通过。</p>
          </>
        )}

        {nt === "SubtitleBurn" && (
          <>
            <label>
              字幕文本
              <input
                value={d.text || d.slogan || ""}
                onChange={(e) => onChange({ text: e.target.value })}
                placeholder="不填就用前面接上的口号；都空就原样通过"
              />
            </label>
            <p className="wf-field-hint">字会叠在画面下方，不会对口型。没写字就原样通过。</p>
          </>
        )}

        {nt === "TtsSpeak" && (
          <>
            <label>
              配音模型
              <select
                value={d.model_id || ttsModels[0]?.model_id || "tts-1"}
                onChange={(e) => onChange({ model_id: e.target.value })}
              >
                {(ttsModels.length ? ttsModels : [{ model_id: "tts-1", label: "tts-1" }]).map((opt) => (
                  <option key={opt.model_id} value={opt.model_id}>
                    {opt.label || opt.model_id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              音色
              <select
                value={d.voice || "zh-CN-XiaoxiaoNeural"}
                onChange={(e) => onChange({ voice: e.target.value })}
              >
                {TTS_VOICES.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              要念的文案
              <textarea
                rows={3}
                value={d.text || d.prompt || ""}
                onChange={(e) => onChange({ text: e.target.value, prompt: e.target.value })}
              />
            </label>
          </>
        )}

        {nt === "SpeechToText" && (
          <>
            <VideoUpload
              value={d.clip_url || d.result_url || d.preview_url || (d.audio_url ? "" : d.media_url) || ""}
              onChange={(url) =>
                onChange({
                  media_url: url,
                  clip_url: url,
                  result_url: url,
                  preview_url: url,
                  stale: false,
                })
              }
            />
            <AudioUpload
              value={d.audio_url || ""}
              onChange={(url) => onChange({ audio_url: url, media_url: url || d.media_url, stale: false })}
            />
            <label>
              听写模型
              <select
                value={d.model_id || asrModels[0]?.model_id || ""}
                onChange={(e) => onChange({ model_id: e.target.value })}
              >
                {asrModels.length === 0 && <option value="">（无可用听写模型）</option>}
                {asrModels.map((opt) => (
                  <option key={opt.model_id} value={opt.model_id}>
                    {opt.label || opt.model_id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              语言
              <select
                value={d.language || "zh"}
                onChange={(e) => onChange({ language: e.target.value })}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
                <option value="auto">自动检测</option>
              </select>
            </label>
            <label>
              识别全文
              <textarea
                rows={5}
                value={d.text || ""}
                onChange={(e) => onChange({ text: e.target.value, prompt: e.target.value })}
                placeholder="跑完会显示全文，可改完再往下传"
              />
            </label>
            <button type="button" className="ghost" disabled={!d.text} onClick={() => void copyText(d.text || "")}>
              复制全文
            </button>
            <label>
              字幕稿
              <textarea
                rows={6}
                value={d.srt || ""}
                onChange={(e) => onChange({ srt: e.target.value })}
                placeholder="跑完会显示字幕稿，可复制到剪辑软件"
              />
            </label>
            <button type="button" className="ghost" disabled={!d.srt} onClick={() => void copyText(d.srt || "")}>
              复制字幕稿
            </button>
            <p className="wf-field-hint">左边接视频或音频。全文可接到写镜头或加字幕；字幕稿可复制出去。</p>
          </>
        )}

        {isLlmNodeType(nt) && (
          <>
            <label>
              用途
              <select
                value={d.llmRole || "shot"}
                onChange={(e) => {
                  const role = e.target.value as "chat" | "brief" | "shot";
                  if (role === "shot") {
                    onChange({
                      llmRole: role,
                      wantNarration: true,
                      system_prompt: shotSystem(true),
                    });
                    return;
                  }
                  onChange({
                    llmRole: role,
                    wantNarration: false,
                    system_prompt: LLM_SYSTEM[role],
                  });
                }}
              >
                <option value="chat">随便聊</option>
                <option value="brief">写品牌简介</option>
                <option value="shot">写这一镜</option>
              </select>
            </label>
            <label>
              写作模型
              <select
                value={d.model_id || llmModels[0]?.model_id || ""}
                onChange={(e) => onChange({ model_id: e.target.value })}
              >
                {llmModels.length === 0 && <option value="">（无可用 LLM）</option>}
                {llmModels.map((opt) => (
                  <option key={opt.model_id} value={opt.model_id}>
                    {opt.label || opt.model_id}
                  </option>
                ))}
              </select>
            </label>
            {(d.llmRole || "shot") === "shot" && (
              <label className="check">
                <input
                  type="checkbox"
                  checked={d.wantNarration !== false}
                  onChange={(e) => {
                    const want = e.target.checked;
                    const cur = d.system_prompt ?? "";
                    const isDefault =
                      !cur || cur === LLM_SYSTEM.shot || cur === LLM_SYSTEM.shotSilent;
                    onChange({
                      wantNarration: want,
                      ...(isDefault ? { system_prompt: shotSystem(want) } : {}),
                      ...(!want ? { narration: "" } : {}),
                    });
                  }}
                />
                同时写口播稿
              </label>
            )}
            <label>
              给模型的要求
              <textarea
                rows={4}
                value={
                  d.system_prompt ??
                  ((d.llmRole || "shot") === "shot"
                    ? shotSystem(d.wantNarration !== false)
                    : LLM_SYSTEM[(d.llmRole || "shot") as keyof typeof LLM_SYSTEM] ?? "")
                }
                onChange={(e) => onChange({ system_prompt: e.target.value })}
              />
            </label>
            <label>
              额外想说的
              <textarea
                rows={3}
                value={d.prompt || d.text || ""}
                onChange={(e) => onChange({ prompt: e.target.value, text: e.target.value })}
                placeholder="可留空：只用前面接上的文案"
              />
            </label>
            <p className="wf-field-hint">
              会调用已启用的对话模型。
              {(d.llmRole || "shot") === "shot"
                ? d.wantNarration === false
                  ? " 这一镜只写画面，不写口播。"
                  : " 这一镜会同时写出画面描述和口播稿。"
                : ""}
            </p>
            {(d.runStatus === "succeeded" || d.narration || d.runOutput?.prompt || d.runOutput?.text) && (
              <div className="wf-run-out">
                <p className="eyebrow">生成结果</p>
                {(d.llmRole || "shot") === "shot" ? (
                  <>
                    <label>
                      画面描述
                      <textarea rows={4} readOnly value={String(d.runOutput?.prompt || d.prompt || "")} />
                    </label>
                    {d.wantNarration !== false && (
                      <label>
                        口播稿
                        <textarea rows={3} readOnly value={String(d.runOutput?.narration || d.narration || "")} />
                      </label>
                    )}
                  </>
                ) : (
                  <label>
                    正文
                    <textarea rows={5} readOnly value={String(d.runOutput?.text || d.text || d.prompt || "")} />
                  </label>
                )}
              </div>
            )}
          </>
        )}

        {onGenerate && (
          <button type="button" className="primary solid" disabled={!canGenerate} onClick={onGenerate}>
            生成这一步
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
          删除这一步
        </button>
      </div>
    </aside>
  );
}
