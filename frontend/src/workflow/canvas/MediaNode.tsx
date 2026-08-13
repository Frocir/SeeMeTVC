import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { STATUS_LABEL } from "../../api";
import { portsFor } from "../ports";
import { normalizeNodeType, type WfData, type WfNodeType } from "../types";

export type MediaNodeData = WfData & {
  onLabelChange?: (label: string) => void;
  onOpenFullscreen?: (url: string, kind: "image" | "video") => void;
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
      label: role === "script" ? "剧本" : role === "prompt" ? "提示词" : "文本",
      tone: "text",
    };
  }
  if (nt === "ImageAsset") return { key: "image", label: "图片", tone: "image" };
  if (nt === "VideoAsset") return { key: "video", label: "视频", tone: "video" };
  if (nt === "ImageToVideo") return { key: "gen", label: "图生视频", tone: "gen" };
  if (nt === "VideoTrim") return { key: "tool", label: "裁时长", tone: "tool" };
  if (nt === "VideoMux") return { key: "tool", label: "拼接", tone: "tool" };
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

function mediaUrl(data: WfData): { kind: "image" | "video" | null; url: string } {
  const fromOut =
    (typeof data.runOutput?.result_url === "string" && data.runOutput.result_url) ||
    (typeof data.runOutput?.clip_url === "string" && data.runOutput.clip_url) ||
    (Array.isArray(data.runOutput?.clips) && typeof data.runOutput.clips[0] === "string"
      ? (data.runOutput.clips[0] as string)
      : "") ||
    "";
  const videoCandidate = data.result_url || data.clip_url || data.preview_url || fromOut || "";
  const nt = normalizeNodeType(data.nodeType);
  const isVideoNode =
    nt === "ImageToVideo" || nt === "VideoAsset" || nt === "VideoTrim" || nt === "VideoMux";

  if (videoCandidate && (isVideoNode || /\.(mp4|webm|mov)(\?|$)/i.test(videoCandidate))) {
    return { kind: "video", url: videoCandidate };
  }
  if (data.image_url) return { kind: "image", url: data.image_url };
  if (videoCandidate) return { kind: "video", url: videoCandidate };
  return { kind: null, url: "" };
}

function emptyHint(data: WfData): string {
  const nt = normalizeNodeType(data.nodeType);
  if (nt === "TextAsset") {
    return (
      [data.slogan, data.prompt, data.text].filter(Boolean).join("\n") ||
      (data.textRole === "script" ? "双击编辑剧本内容" : "输入品牌与卖点")
    );
  }
  if (nt === "ImageAsset") return "拖入或上传参考图";
  if (nt === "VideoTrim") return "连接上游视频后裁剪";
  if (nt === "VideoMux") return "连接多段镜头后拼接";
  if (nt === "ImageToVideo") return "连接提示词与参考图";
  return "等待生成结果";
}

export function MediaNode({ data, selected }: NodeProps<Node<MediaNodeData>>) {
  const ports = portsFor(data.nodeType);
  const inputs = ports?.inputs || [];
  const outputs = ports?.outputs || [];
  const media = mediaUrl(data);
  const st = data.runStatus;
  const meta = kindMeta(data.nodeType, data);
  const nt = normalizeNodeType(data.nodeType);

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
          className={`cv-media ${media.kind ? `has-${media.kind}` : "is-empty"} ${nt === "TextAsset" ? "is-text" : ""}`}
          onDoubleClick={(e) => {
            e.stopPropagation();
            if (media.url && media.kind) data.onOpenFullscreen?.(media.url, media.kind);
          }}
        >
          {media.kind === "video" && media.url ? (
            <video src={media.url} playsInline controls onClick={(e) => e.stopPropagation()} />
          ) : media.kind === "image" && media.url ? (
            <img src={media.url} alt="" />
          ) : (
            <div className="cv-media-empty">
              <div className="cv-empty-icon">
                <KindIcon tone={meta.tone} />
              </div>
              <span>{emptyHint(data)}</span>
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
