import { useRef, useState } from "react";
import { uploadImage, uploadVideo } from "../api";

type Props = {
  open: boolean;
  nodeLabel: string;
  errorMessage: string;
  onClose: () => void;
  onApply: (url: string, continueDownstream: boolean) => void;
};

export default function AdminSimulateDialog({
  open,
  nodeLabel,
  errorMessage,
  onClose,
  onApply,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [cont, setCont] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (!open) return null;

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setErr("");
    try {
      if (file.type.startsWith("image/")) {
        const res = await uploadImage(file);
        setUrl(res.url);
      } else if (file.type.startsWith("video/")) {
        const res = await uploadVideo(file);
        setUrl(res.url);
      } else {
        setErr("请上传图片或视频文件");
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "上传失败");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="cv-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="cv-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sim-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="sim-title">使用外部素材模拟生成</h2>
        <p className="cv-modal-lead">
          节点「{nodeLabel}」失败。您可使用其他产品生成素材，粘贴到此处，模拟本产品的生成结果。
        </p>
        {errorMessage && <p className="error">{errorMessage}</p>}
        <label>
          素材 URL
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://… 或上传后自动填入"
          />
        </label>
        <div className="cv-modal-row">
          <input
            ref={fileRef}
            type="file"
            accept="image/*,video/*"
            hidden
            onChange={(e) => void onFile(e.target.files?.[0])}
          />
          <button type="button" className="ghost" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? "上传中…" : "本地上传"}
          </button>
        </div>
        {err && <p className="error">{err}</p>}
        <label className="check">
          <input type="checkbox" checked={cont} onChange={(e) => setCont(e.target.checked)} />
          填入并继续下游
        </label>
        <div className="cv-modal-actions">
          <button type="button" className="ghost" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="primary solid"
            disabled={!url.trim()}
            onClick={() => onApply(url.trim(), cont)}
          >
            填入结果
          </button>
        </div>
      </div>
    </div>
  );
}
