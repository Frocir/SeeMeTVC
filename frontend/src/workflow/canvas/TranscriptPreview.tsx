import type { WfData } from "../types";

type Props = {
  data: WfData;
};

function transcriptText(data: WfData): string {
  const out = data.runOutput || {};
  return String(out.text || data.text || "").trim();
}

function segmentCount(data: WfData): number {
  const out = data.runOutput || {};
  const segs = Array.isArray(out.segments) ? out.segments : Array.isArray(data.segments) ? data.segments : [];
  return segs.length;
}

export default function TranscriptPreview({ data }: Props) {
  const text = transcriptText(data);
  const segs = segmentCount(data);
  const srt = String(data.runOutput?.srt || data.srt || "").trim();
  if (!text && !srt) {
    return (
      <div className="cv-transcript is-empty">
        <span>连接视频或音频后提取口播</span>
      </div>
    );
  }
  return (
    <div className="cv-transcript">
      <div className="cv-transcript-meta">
        <strong>{segs ? `${segs} 段` : "全文"}</strong>
        {srt ? <span>含 SRT</span> : null}
      </div>
      <span className="cv-transcript-copy">{text || srt}</span>
    </div>
  );
}
