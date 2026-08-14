import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { STATUS_LABEL } from "../../api";
import { portsFor } from "../ports";
import { normalizeNodeType, type WfData, type WfNodeType } from "../types";

export type MediaNodeData = WfData & {
  onLabelChange?: (label: string) => void;
  onOpenFullscreen?: (url: string, kind: "image" | "video" | "audio") => void;
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
      label: role === "prompt" ? "提示词" : "文本",
      tone: "text",
    };
  }
  if (nt === "ImageAsset") return { key: "image", label: "图片", tone: "image" };
  if (nt === "VideoAsset") return { key: "video", label: "视频", tone: "video" };
  if (nt === "AudioAsset") return { key: "audio", label: "音频", tone: "audio" };
  if (nt === "TextToImage") return { key: "image", label: "文生图", tone: "image" };
  if (nt === "ImageToVideo") return { key: "gen", label: "图生视频", tone: "gen" };
  if (nt === "VideoTrim") return { key: "tool", label: "裁时长", tone: "tool" };
  if (nt === "VideoMux") return { key: "tool", label: "拼接", tone: "tool" };
  if (nt === "MixAudio") return { key: "audio", label: "混音", tone: "audio" };
  if (nt === "VideoDemux") return { key: "tool", label: "拆音轨", tone: "tool" };
  if (nt === "AudioTrim") return { key: "audio", label: "音频裁切", tone: "audio" };
  if (nt === "SubtitleBurn") return { key: "tool", label: "字幕", tone: "tool" };
  if (nt === "TtsSpeak") return { key: "audio", label: "TTS", tone: "audio" };
  if (nt === "LlmText") return { key: "text", label: "LLM", tone: "text" };
  return { key: "asset", label: "节点", tone: "asset" };
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
  const isImageNode = nt === "ImageAsset" || nt === "TextToImage";

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

function textPreview(data: WfData): string {
  const nt = normalizeNodeType(data.nodeType);
  if (nt === "LlmText") return llmPreview(data);
  if (nt === "TextAsset") {
    return [data.slogan, data.prompt, data.text].filter(Boolean).join("\n");
  }
  if (nt === "TextToImage" || nt === "ImageToVideo") {
    return String(data.prompt || data.text || "").trim();
  }
  if (nt === "TtsSpeak") return String(data.text || data.narration || "").trim();
  if (nt === "SubtitleBurn") return String(data.slogan || data.text || "").trim();
  return "";
}

function emptyHint(data: WfData): string {
  const nt = normalizeNodeType(data.nodeType);
  if (nt === "TextAsset") return "输入品牌与卖点";
  if (nt === "ImageAsset") return "拖入或上传参考图";
  if (nt === "VideoAsset") return "上传视频片段";
  if (nt === "AudioAsset") return "上传 BGM 或口播文件";
  if (nt === "VideoTrim") return "连接上游视频后裁剪";
  if (nt === "VideoMux") return "连接多段镜头后拼接";
  if (nt === "MixAudio") return "接满视频、BGM、口播";
  if (nt === "VideoDemux") return "连接有声视频后拆轨";
  if (nt === "AudioTrim") return "连接音频后裁切";
  if (nt === "SubtitleBurn") return "连接成片后烧 slogan";
  if (nt === "TtsSpeak") return "连接旁白或填写口播稿";
  if (nt === "LlmText") return "连接 Brief";
  if (nt === "TextToImage") return "连接提示词后出图";
  if (nt === "ImageToVideo") return "连接提示词与参考图";
  return "等待生成结果";
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
      className={`cv-node tone-${meta.tone} ${selected ? "selected" : ""} ${st ? `st-${st}` : ""} ${data.stale ? "stale" : ""} ${data.simulated ? "simulated" : ""}`}
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
            {data.simulated && <span className="cv-badge sim">模拟</span>}
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
          {media.kind === "video" && media.url ? (
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
