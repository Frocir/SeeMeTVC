import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";
import { BEAUTY_PROMOS } from "../beautyAssets";

const heroTiles = BEAUTY_PROMOS.slice(0, 3);

export default function LoginPage() {
  const { me, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  // Dev convenience: prefill bootstrap admin (keep for local iteration).
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("admin123456");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-shell">
        <div className="auth-hero">
          <div className="auth-hero-mosaic">
            {heroTiles.map((tile) => (
              <div key={tile.id} className="auth-tile" data-label={tile.tag}>
                <img src={tile.image} alt={tile.title} />
              </div>
            ))}
          </div>
          <div className="auth-hero-copy">
            <p className="eyebrow">面部美妆 · TVC 成片</p>
            <h1 className="brand-mark">为美妆品牌拍出能上线的广告片</h1>
            <p className="lead">
              唇釉微距、底妆贴合、精华光感——面向面部美妆垂类的轻度 Seedance 工作室，素材即点即拍。
            </p>
          </div>
        </div>

        <div className="auth-panel">
          <h1>{mode === "login" ? "进入美妆工作室" : "创建品牌账号"}</h1>
          <p className="muted">并行生成广告片 · 回看历史成片 · 余额清晰</p>
          <form onSubmit={onSubmit}>
            {mode === "register" && (
              <label>
                昵称 / 品牌名
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </label>
            )}
            <label>
              邮箱
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                type="email"
                required
                autoComplete="username"
              />
            </label>
            <label>
              密码
              <input
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                type="password"
                required
                minLength={6}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
            </label>
            {error && <p className="error">{error}</p>}
            <button type="submit" className="block primary" disabled={busy}>
              {busy ? "处理中…" : mode === "login" ? "开始创作" : "注册并开始"}
            </button>
          </form>
          <button
            type="button"
            className="linkish"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
          >
            {mode === "login" ? "没有账号？注册" : "已有账号？登录"}
          </button>
          {mode === "login" && (
            <p className="auth-demo-hint muted">开发阶段已预填本地超管账号，上线前请去掉。</p>
          )}
        </div>
      </div>
    </div>
  );
}
