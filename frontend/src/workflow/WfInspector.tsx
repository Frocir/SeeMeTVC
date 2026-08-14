import { useRef, useState } from "react";
import ReferenceImageField from "../components/ReferenceImageField";
import { uploadAudio, uploadVideo, type ModelOption } from "../api";
import { PROMPT_SNIPPETS, type PromptBucket } from "./prompts";
import { LLM_SYSTEM, TTS_VOICES, shotSystem } from "./templates";
import { isLlmNodeType, normalizeNodeType, type WfData } from "./types";

type Props = {
  data: WfData | null;
  models: ModelOption[];
  llmModels?: ModelOption[];
  ttsModels?: ModelOption[];
  imageModels?: ModelOption[];
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
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="/uploads/… 或上传" />
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
      <p className="wf-field-hint">mp3 / wav / m4a / aac。官方模板预填演示床垫，可替换。</p>
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
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="/uploads/… 或上传 mp4/webm/mov" />
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
      <p className="wf-field-hint">mp4 / webm / mov。可接到视频反推、裁切、拆音轨等节点。</p>
    </>
  );
}

export default function WfInspector({
  data,
  models,
  llmModels = [],
  ttsModels = [],
  imageModels = [],
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
          </>
        )}

        {nt === "ImageAsset" && (
          <>
            <ReferenceImageField
              value={d.image_url || ""}
              onChange={(url) => onChange({ image_url: url, stale: false })}
              label="图片"
              hint="上传或粘贴 URL。可接到文生图的参考图口，或图生视频。"
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
              反推说明 / Brief
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
              固定抽帧数量
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
              最大分镜数
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
              切镜阈值
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
              采样 FPS
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
              Prompt 风格
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
                从分镜生成工作流
              </button>
              <button
                type="button"
                className="ghost"
                disabled={!canExpandScenes}
                onClick={() => onExpandScenes?.("silent")}
              >
                仅生成视频镜头
              </button>
            </div>
            <p className="wf-field-hint">运行后会输出分析文本、Seedance prompt、关键帧、时间轴和 scenes，可一键展开为多镜头工作流。</p>
          </>
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
              必须 <strong>结束秒 &gt; 起始秒</strong>。默认对齐图生时长（5 秒）。若结束秒超过片长，ffmpeg 可能失败。
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

        {nt === "AudioAsset" && (
          <AudioUpload
            value={d.audio_url || ""}
            onChange={(url) => onChange({ audio_url: url, stale: false })}
          />
        )}

        {nt === "MixAudio" && (
          <p className="wf-field-hint">
            必须接满 <strong>video + BGM + 口播</strong> 三口，缺一则整单失败。BGM 循环到画面时长；口播不循环、超长裁切。
          </p>
        )}

        {nt === "VideoDemux" && (
          <p className="wf-field-hint">
            有声视频 → 静音画面 + 音轨。<strong>无音轨会整单失败</strong>。官方模板未预接；2.5
            原声会叠在混音下，要干净请先接本节点。
          </p>
        )}

        {nt === "TextToImage" && (
          <>
            <label>
              文生图模型
              <select
                value={d.model_id || imageModels[0]?.model_id || "t2i-local-simulate"}
                onChange={(e) => onChange({ model_id: e.target.value })}
              >
                {(imageModels.length
                  ? imageModels
                  : [{ model_id: "t2i-local-simulate", label: "本地文生图模拟", cost_per_second: 0, provider: "mock" }]
                ).map((opt) => (
                  <option key={opt.model_id} value={opt.model_id}>
                    {opt.label || opt.model_id}
                    {opt.cost_per_second ? ` · ${opt.cost_per_second}/张` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              提示词（可被上游覆盖）
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
              hint="有图则按图生图意图；本轮模拟仍返回同一张占位图。"
            />
            <p className="wf-field-hint">
              本地模拟不扣费；真图像渠道按「每张图片」扣费，Agent 触发生成时会先弹确认卡。
            </p>
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
            <p className="wf-field-hint">结束秒为 0 或不大于起始秒时，整段直通。</p>
          </>
        )}

        {nt === "SubtitleBurn" && (
          <>
            <label>
              字幕文本
              <input
                value={d.text || d.slogan || ""}
                onChange={(e) => onChange({ text: e.target.value })}
                placeholder="空则用上游口号；都空则直通"
              />
            </label>
            <p className="wf-field-hint">烧在画面下部。不对口型。无字则直通视频，不失败。</p>
          </>
        )}

        {nt === "TtsSpeak" && (
          <>
            <label>
              TTS 模型
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
              口播文本（可被上游 narration 覆盖）
              <textarea
                rows={3}
                value={d.text || d.prompt || ""}
                onChange={(e) => onChange({ text: e.target.value, prompt: e.target.value })}
              />
            </label>
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
                <option value="chat">对话</option>
                <option value="brief">Brief</option>
                <option value="shot">单镜</option>
              </select>
            </label>
            <label>
              LLM 模型
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
                输出旁白
              </label>
            )}
            <label>
              System prompt
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
              用户补充
              <textarea
                rows={3}
                value={d.prompt || d.text || ""}
                onChange={(e) => onChange({ prompt: e.target.value, text: e.target.value })}
                placeholder="可空：只用上游 text"
              />
            </label>
            <p className="wf-field-hint">
              {(d.model_id || llmModels[0]?.model_id) === "llm-local-simulate"
                ? "本地 LLM 模拟：即时返回，不调上游。"
                : "真模型会走外网；约 20 秒未响应即失败。演示请改选「本地 LLM 模拟」。"}
              {(d.llmRole || "shot") === "shot"
                ? d.wantNarration === false
                  ? " 单镜只出画面 prompt，不写旁白。"
                  : " 单镜输出 JSON：prompt + narration。解析失败整单失败。"
                : ""}
            </p>
            {(d.runStatus === "succeeded" || d.narration || d.runOutput?.prompt || d.runOutput?.text) && (
              <div className="wf-run-out">
                <p className="eyebrow">生成结果</p>
                {(d.llmRole || "shot") === "shot" ? (
                  <>
                    <label>
                      画面 prompt
                      <textarea rows={4} readOnly value={String(d.runOutput?.prompt || d.prompt || "")} />
                    </label>
                    {d.wantNarration !== false && (
                      <label>
                        旁白 narration
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
