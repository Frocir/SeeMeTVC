import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";
import { BEAUTY_PROMOS, HARDWARE_PROMOS } from "../beautyAssets";

const heroTiles = [
  { ...BEAUTY_PROMOS[2], kindLabel: "香氛" },
  { ...BEAUTY_PROMOS[0], kindLabel: "唇妆" },
  { ...HARDWARE_PROMOS.find((p) => p.id === "hw-ai-glasses")!, kindLabel: "AI 眼镜" },
  { ...BEAUTY_PROMOS[1], kindLabel: "护肤" },
];

const ADVANTAGES = [
  { n: "01", t: "Lookbook 即开工", d: "美妆与 AI 硬件模板" },
  { n: "02", t: "节点可改可重跑", d: "Auto 直出，或 Plan 分环" },
  { n: "03", t: "按生成扣积分", d: "同一画布出片，账目清楚" },
];

export default function LoginPage() {
  const { me, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const demo = typeof __DEV_LOGIN__ !== "undefined" ? __DEV_LOGIN__ : { email: "", password: "" };
  const [email, setEmail] = useState(demo.email);
  const [password, setPassword] = useState(demo.password);
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
          <div className="auth-hero-top">
            <span className="auth-seal" aria-hidden>
              GP
            </span>
            <span className="auth-hero-kicker">Beauty · Hardware · Film</span>
          </div>
          <div className="auth-hero-name">
            <h1 className="auth-wordmark">
              <em>Glam</em>Pilot
            </h1>
            <p className="auth-tagline">把 brief 变成能改、能再跑的成片工作流</p>
          </div>
          <div className="auth-hero-mosaic" aria-hidden>
            {heroTiles.map((tile) => (
              <div
                key={tile.id}
                className={`auth-tile is-${tile.kind === "hardware" ? "hardware" : "beauty"}`}
                data-label={tile.kindLabel}
              >
                <img src={tile.image} alt="" />
              </div>
            ))}
          </div>
          <ol className="auth-feats">
            {ADVANTAGES.map((item) => (
              <li key={item.n}>
                <span>{item.n}</span>
                <strong>{item.t}</strong>
                <em>{item.d}</em>
              </li>
            ))}
          </ol>
        </div>

        <div className="auth-panel">
          <span className="auth-panel-seal" aria-hidden>
            GP
          </span>
          <h1>{mode === "login" ? "进入工作区" : "创建品牌账号"}</h1>
          <p className="muted">用账号打开你的 GlamPilot 画布</p>
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
          {mode === "login" && demo.email && (
            <p className="auth-demo-hint muted">开发阶段已预填本地超管账号（来自仓库根目录 .env）。</p>
          )}
        </div>
      </div>
    </div>
  );
}
