import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { STATUS_LABEL } from "../../api";
import { portsFor } from "../ports";
import { NODE_TYPE_LABEL } from "../labels";
import { normalizeNodeType, type Scene, type TimelineItem, type WfData, type WfNodeType } from "../types";
import ImageCompareView from "./ImageCompareView";
import TranscriptPreview from "./TranscriptPreview";

export type MediaNodeData = WfData & {
  onLabelChange?: (label: string) => void;
  onOpenFullscreen?: (url: string, kind: "image" | "video" | "audio") => void;
  onPatch?: (patch: Partial<WfData>) => void;
};

type KindMeta = {
  key: string;
  label: string;
  tone: string;
};

function kindMeta(nodeType: WfNodeType, data: WfData): KindMeta {
  const nt = normalizeNodeType(nodeType);
  if (nt === "TextAsset") {
    const role = data.textRole || "brief";
    return {
      key: "text",
      label: role === "prompt" ? "提示词" : role === "notes" ? "备注" : "文案",
      tone: "text",
    };
  }
  const toneBy: Record<string, string> = {
    ImageAsset: "image",
    VideoAsset: "video",
    AudioAsset: "audio",
    TextToImage: "image",
    ImageCompare: "image",
    SpeechToText: "text",
    ImageToVideo: "gen",
    VideoTrim: "tool",
    VideoMux: "tool",
    MixAudio: "audio",
    VideoDemux: "tool",
    VideoReversePrompt: "text",
    AudioTrim: "audio",
    SubtitleBurn: "tool",
    TtsSpeak: "audio",
    LlmText: "text",
  };
  return {
    key: toneBy[nt] || "asset",
    label: NODE_TYPE_LABEL[nt] || "步骤",
    tone: toneBy[nt] || "asset",
  };
}

function KindIcon({ tone }: { tone: string }) {
  if (tone === "text") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path
          fill="currentColor"
          d="M5 5h14v2.2H13.7V19h-3.4V7.2H5V5Z"
        />
      </svg>
    );
  }
  if (tone === "image") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path
          fill="currentColor"
          d="M4.5 5.5A1.5 1.5 0 0 1 6 4h12a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 18 20H6a1.5 1.5 0 0 1-1.5-1.5v-13ZM8 9.2a1.3 1.3 0 1 0 0-2.6 1.3 1.3 0 0 0 0 2.6Zm10 7.3-4.6-5.4a.8.8 0 0 0-1.2 0L8.4 16.5H18Z"
        />
      </svg>
    );
  }
  if (tone === "video" || tone === "gen") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path
          fill="currentColor"
          d="M4 6.5A2.5 2.5 0 0 1 6.5 4h7A2.5 2.5 0 0 1 16 6.5v11A2.5 2.5 0 0 1 13.5 20h-7A2.5 2.5 0 0 1 4 17.5v-11Zm13.2 2.1 3.1-1.8a1 1 0 0 1 1.5.9v7.6a1 1 0 0 1-1.5.9l-3.1-1.8V8.6Z"
        />
      </svg>
    );
  }
  if (tone === "audio") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden>
        <path
          fill="currentColor"
          d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6Z"
        />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <path
        fill="currentColor"
        d="M11 4.5h2v5.2l3.7-3.7 1.4 1.4-3.7 3.7H19.5v2h-5.1l3.7 3.7-1.4 1.4-3.7-3.7V19.5h-2v-5.1l-3.7 3.7-1.4-1.4 3.7-3.7H4.5v-2h5.1L5.9 7.4l1.4-1.4 3.7 3.7V4.5Z"
      />
    </svg>
  );
}

function handleTop(index: number, total: number): string {
  if (total <= 1) return "50%";
  const step = 100 / (total + 1);
  return `${step * (index + 1)}%`;
}

function mediaUrl(data: WfData): { kind: "image" | "video" | "audio" | null; url: string } {
  const fromOut =
    (typeof data.runOutput?.result_url === "string" && data.runOutput.result_url) ||
    (typeof data.runOutput?.clip_url === "string" && data.runOutput.clip_url) ||
    (typeof data.runOutput?.image_url === "string" && data.runOutput.image_url) ||
    (typeof data.runOutput?.audio_url === "string" && data.runOutput.audio_url) ||
    (Array.isArray(data.runOutput?.clips) && typeof data.runOutput.clips[0] === "string"
      ? (data.runOutput.clips[0] as string)
      : "") ||
    "";
  const videoCandidate = data.result_url || data.clip_url || data.preview_url || "";
  const audioCandidate = data.audio_url || "";
  const nt = normalizeNodeType(data.nodeType);
  const isVideoNode =
    nt === "ImageToVideo" ||
    nt === "VideoAsset" ||
    nt === "VideoTrim" ||
    nt === "VideoMux" ||
    nt === "MixAudio" ||
    nt === "VideoDemux" ||
    nt === "SubtitleBurn";
  const isAudioNode = nt === "AudioAsset" || nt === "TtsSpeak" || nt === "AudioTrim";
  const isImageNode = nt === "ImageAsset" || nt === "TextToImage" || nt === "ImageCompare";

  if (isAudioNode && (audioCandidate || fromOut)) {
    const url = audioCandidate || fromOut;
    if (url && /\.(mp3|wav|m4a|aac)(\?|$)/i.test(url)) return { kind: "audio", url };
    if (url) return { kind: "audio", url };
  }
  if (videoCandidate && (isVideoNode || /\.(mp4|webm|mov)(\?|$)/i.test(videoCandidate))) {
    return { kind: "video", url: videoCandidate };
  }
  if (fromOut && isVideoNode) return { kind: "video", url: fromOut };
  if ((data.image_url || fromOut) && (isImageNode || nt === "ImageToVideo")) {
    return { kind: "image", url: data.image_url || fromOut };
  }
  if (data.image_url) return { kind: "image", url: data.image_url };
  if (audioCandidate) return { kind: "audio", url: audioCandidate };
  if (videoCandidate) return { kind: "video", url: videoCandidate };
  return { kind: null, url: "" };
}

function llmPreview(data: WfData): string {
  const out = data.runOutput || {};
  const prompt = String(out.prompt || data.prompt || "").trim();
  const narration = String(out.narration || data.narration || "").trim();
  const text = String(out.text || data.text || "").trim();
  const role = data.llmRole || "shot";
  if (role === "shot" && (prompt || narration)) {
    const lines = [prompt && `画面：${prompt}`];
    if (data.wantNarration !== false && narration) lines.push(`旁白：${narration}`);
    return lines.filter(Boolean).join("\n");
  }
  return text || prompt || narration;
}

function reverseFrames(data: WfData): string[] {
  const out = data.runOutput || {};
  const fromOut = Array.isArray(out.frames) ? out.frames.filter((x): x is string => typeof x === "string") : [];
  return fromOut.length ? fromOut : data.frames || [];
}

function reverseScenes(data: WfData): Scene[] {
  const out = data.runOutput || {};
  const fromOut = Array.isArray(out.scenes) ? (out.scenes as Scene[]) : [];
  return fromOut.length ? fromOut : data.scenes || [];
}

function reverseTimeline(data: WfData): TimelineItem[] {
  const out = data.runOutput || {};
  const fromOut = Array.isArray(out.timeline) ? (out.timeline as TimelineItem[]) : [];
  return fromOut.length ? fromOut : data.timeline || [];
}

function textPreview(data: WfData): string {
  const nt = normalizeNodeType(data.nodeType);
  if (nt === "LlmText") return llmPreview(data);
  if (nt === "TextAsset") {
    return String(data.prompt || data.text || "").trim();
  }
  if (nt === "VideoReversePrompt") {
    const out = data.runOutput || {};
    const prompt = String(out.prompt || data.prompt || "").trim();
    const text = String(out.text || data.text || "").trim();
    const scenes = reverseScenes(data).length;
    const frames = reverseFrames(data).length;
    return [text, prompt, scenes ? `分镜：${scenes} 个 Clip` : "", frames ? `关键帧：${frames} 张` : ""]
      .filter(Boolean)
      .join("\n");
  }
  if (nt === "TextToImage" || nt === "ImageToVideo") {
    return String(data.prompt || data.text || "").trim();
  }
  if (nt === "TtsSpeak") return String(data.text || data.narration || "").trim();
  if (nt === "SpeechToText") {
    const out = data.runOutput || {};
    return String(out.text || data.text || out.srt || data.srt || "").trim();
  }
  if (nt === "SubtitleBurn") return String(data.slogan || data.text || "").trim();
  return "";
}

function ReversePreview({ data, copy }: { data: WfData; copy: string }) {
  const frames = reverseFrames(data).slice(0, 4);
  const scenes = reverseScenes(data);
  const timeline = reverseTimeline(data);
  if (!frames.length && !scenes.length) return null;
  return (
    <div className="cv-reverse-preview">
      {frames.length > 0 && (
        <div className="cv-frame-grid">
          {frames.map((url, idx) => (
            <img key={`${url}-${idx}`} src={url} alt="" />
          ))}
        </div>
      )}
      <div className="cv-reverse-meta">
        <strong>{scenes.length || timeline.length} 个分镜</strong>
        {timeline[0] && timeline[timeline.length - 1] && (
          <span>
            {timeline[0].start_time?.toFixed?.(1) ?? timeline[0].start_time}s–
            {timeline[timeline.length - 1].end_time?.toFixed?.(1) ?? timeline[timeline.length - 1].end_time}s
          </span>
        )}
      </div>
      {copy && <span className="cv-reverse-copy">{copy}</span>}
    </div>
  );
}

function emptyHint(data: WfData): string {
  const nt = normalizeNodeType(data.nodeType);
  if (nt === "TextAsset") return "写品牌、卖点和口号";
  if (nt === "ImageAsset") return "上传产品图或人物图";
  if (nt === "VideoAsset") return "上传参考片或成片";
  if (nt === "AudioAsset") return "上传配乐或旁白";
  if (nt === "VideoTrim") return "接上视频后截取几秒";
  if (nt === "VideoMux") return "接上几段视频后拼成一条";
  if (nt === "MixAudio") return "接上视频、配乐和口播";
  if (nt === "VideoDemux") return "接上有声视频后拆出声音";
  if (nt === "VideoReversePrompt") return "接上参考片后拆分镜";
  if (nt === "AudioTrim") return "接上音频后截取几秒";
  if (nt === "SubtitleBurn") return "接上成片后叠一句字";
  if (nt === "TtsSpeak") return "接上口播稿，或自己填写";
  if (nt === "LlmText") return "接上文案后写这一镜";
  if (nt === "TextToImage") return "接上画面描述后出图";
  if (nt === "ImageCompare") return "接上两张图后对比";
  if (nt === "SpeechToText") return "接上视频或音频后听写";
  if (nt === "ImageToVideo") return "接上画面描述和首帧图";
  return "还没有结果";
}

export function MediaNode({ data, selected }: NodeProps<Node<MediaNodeData>>) {
  const ports = portsFor(data.nodeType, data);
  const inputs = ports?.inputs || [];
  const outputs = ports?.outputs || [];
  const media = mediaUrl(data);
  const st = data.runStatus;
  const meta = kindMeta(data.nodeType, data);
  const nt = normalizeNodeType(data.nodeType);
  const copy = textPreview(data);
  const isTextCard = nt === "TextAsset" || nt === "LlmText" || (!media.kind && Boolean(copy));

  return (
    <div
      className={`cv-node tone-${meta.tone} ${selected ? "selected" : ""} ${st ? `st-${st}` : ""} ${data.stale ? "stale" : ""}`}
    >
      {inputs.map((p, i) => (
        <Handle
          key={`in-${p.id}`}
          id={p.id}
          type="target"
          position={Position.Left}
          className={`cv-handle cv-handle-in kind-${p.kind}`}
          style={{ top: handleTop(i, inputs.length) }}
          title={p.label}
        />
      ))}

      <div className="cv-card">
        <div className="cv-card-top">
          <span className={`cv-kind tone-${meta.tone}`}>
            <KindIcon tone={meta.tone} />
            {meta.label}
          </span>
          <span className="cv-card-flags">
            {data.stale && <span className="cv-badge stale">过期</span>}
            {st === "running" && <span className="cv-badge run">生成中</span>}
            {st && st !== "succeeded" && st !== "running" && (
              <span className="cv-badge err">{STATUS_LABEL[st] || st}</span>
            )}
          </span>
        </div>

        <div
          className={`cv-media ${media.kind ? `has-${media.kind}` : "is-empty"} ${isTextCard ? "is-text" : ""} ${copy ? "has-copy" : ""}`}
          onDoubleClick={(e) => {
            e.stopPropagation();
            if (media.url && media.kind) data.onOpenFullscreen?.(media.url, media.kind);
          }}
        >
          {nt === "SpeechToText" ? (
            <TranscriptPreview data={data} />
          ) : nt === "ImageCompare" ? (
            <ImageCompareView
              data={data}
              onPatch={data.onPatch}
              onOpenFullscreen={data.onOpenFullscreen}
            />
          ) : nt === "VideoReversePrompt" && (reverseFrames(data).length > 0 || reverseScenes(data).length > 0) ? (
            <ReversePreview data={data} copy={copy} />
          ) : media.kind === "video" && media.url ? (
            <video src={media.url} playsInline controls onClick={(e) => e.stopPropagation()} />
          ) : media.kind === "audio" && media.url ? (
            <audio src={media.url} controls onClick={(e) => e.stopPropagation()} />
          ) : media.kind === "image" && media.url ? (
            <img src={media.url} alt="" />
          ) : (
            <div className={`cv-media-empty ${copy ? "has-copy" : ""}`}>
              {!copy && (
                <div className="cv-empty-icon">
                  <KindIcon tone={meta.tone} />
                </div>
              )}
              <span>{copy || emptyHint(data)}</span>
            </div>
          )}
          {st === "running" && (
            <div className="cv-media-overlay">
              <div className="cv-spinner" />
              <span>生成中</span>
            </div>
          )}
          <div className="cv-media-shine" aria-hidden />
        </div>

        <div className="cv-card-foot">
          <input
            className="cv-node-name nodrag nopan"
            value={data.label}
            placeholder="未命名"
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => data.onLabelChange?.(e.target.value)}
            onKeyDown={(e) => e.stopPropagation()}
          />
          {(inputs.length > 0 || outputs.length > 0) && (
            <div className="cv-port-hints">
              {inputs.map((p) => (
                <span key={`ih-${p.id}`} className="in">
                  {p.label}
                </span>
              ))}
              {outputs.map((p) => (
                <span key={`oh-${p.id}`} className="out">
                  {p.label}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {outputs.map((p, i) => (
        <Handle
          key={`out-${p.id}`}
          id={p.id}
          type="source"
          position={Position.Right}
          className={`cv-handle cv-handle-out kind-${p.kind}`}
          style={{ top: handleTop(i, outputs.length) }}
          title={p.label}
        />
      ))}
    </div>
  );
}

export const mediaNodeTypes = { media: MediaNode };
