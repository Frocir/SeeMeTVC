import { useRef, useState } from "react";
import { uploadImage } from "../api";

type Props = {
  value: string;
  onChange: (url: string) => void;
  label?: string;
  hint?: string;
  placeholder?: string;
  disabled?: boolean;
  disabledHint?: string;
};

export default function ReferenceImageField({
  value,
  onChange,
  label = "参考图",
  hint = "可粘贴 URL，或从本地上传",
  placeholder = "https://… 或上传后自动填入",
  disabled = false,
  disabledHint,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const res = await uploadImage(file);
      onChange(res.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className={`ref-image-field ${disabled ? "is-disabled" : ""}`}>
      <label>
        {label}
        <span className="field-hint">{disabled ? disabledHint || hint : hint}</span>
        <div className="ref-image-row">
          <input
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            disabled={disabled}
          />
          <button
            type="button"
            className="ghost"
            disabled={busy || disabled}
            onClick={() => inputRef.current?.click()}
          >
            {busy ? "上传中…" : "上传"}
          </button>
        </div>
      </label>
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif"
        hidden
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      {error && <p className="error">{error}</p>}
      {value && (
        <div className="ref-image-preview">
          <img src={value} alt="参考图预览" />
          <button type="button" className="ghost danger" disabled={disabled} onClick={() => onChange("")}>
            清除
          </button>
        </div>
      )}
    </div>
  );
}
