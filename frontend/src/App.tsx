import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useRef, useState, type ReactNode } from "react";
import { api, type BalanceEntry } from "./api";
import { useAuth } from "./auth";
import LedgerModal from "./components/LedgerModal";
import AdminPage from "./pages/AdminPage";
import CharactersPage from "./pages/CharactersPage";
import LoginPage from "./pages/LoginPage";
import StudioPage from "./pages/StudioPage";
import TemplatesPage from "./pages/TemplatesPage";
import WorkflowCanvasPage from "./pages/WorkflowCanvasPage";
import WorkspacePage from "./pages/WorkspacePage";
import { useShowAdmin, setShowAdmin } from "./flags";

const RAIL = [
  { to: "/", icon: "▦", label: "工作区", end: true },
  { to: "/templates", icon: "▤", label: "模板" },
  { to: "/characters", icon: "♙", label: "人物" },
] as const;

function Shell({ children, wide }: { children: ReactNode; wide?: boolean }) {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const showAdmin = useShowAdmin();
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledger, setLedger] = useState<BalanceEntry[] | null>(null);
  const [ledgerError, setLedgerError] = useState("");
  const avatarClicks = useRef({ n: 0, t: 0 });

  async function openLedger() {
    setLedgerOpen(true);
    setLedger(null);
    setLedgerError("");
    try {
      setLedger(await api<BalanceEntry[]>("/api/me/ledger"));
    } catch (e) {
      setLedgerError(e instanceof Error ? e.message : "加载失败");
    }
  }

  const initial = (me?.display_name || me?.email || "?").slice(0, 1);

  function onAvatarClick() {
    if (me?.role !== "super_admin") return;
    const now = Date.now();
    if (now - avatarClicks.current.t > 2000) avatarClicks.current.n = 0;
    avatarClicks.current.t = now;
    avatarClicks.current.n += 1;
    if (avatarClicks.current.n < 5) return;
    avatarClicks.current.n = 0;
    const next = !showAdmin;
    setShowAdmin(next);
    navigate(next ? "/admin" : "/");
  }

  return (
    <div className="app">
      <aside className="rail">
        <div className="logo" title="GlamPilot">
          GP
        </div>
        <nav>
          {RAIL.map((r) => (
            <NavLink key={r.to} to={r.to} end={r.to === "/"} title={r.label}>
              <span className="ico">{r.icon}</span>
              <span>{r.label}</span>
            </NavLink>
          ))}
          {showAdmin && me?.role === "super_admin" && (
            <NavLink to="/admin" title="超管">
              <span className="ico">⌘</span>
              <span>超管</span>
            </NavLink>
          )}
        </nav>
      </aside>
      <div className="shell">
        <header className="topbar">
          <span className="eyebrow" style={{ margin: 0 }}>
            GlamPilot
          </span>
          <div className="top-actions">
            {me && (
              <button className="balance-chip" type="button" onClick={() => void openLedger()}>
                余额 <em>{me.balance.toFixed(2)}</em> {me.balance_unit}
              </button>
            )}
            <span className="account">
              <span className="avatar" onClick={onAvatarClick}>
                {initial}
              </span>
              <span>{me?.display_name || me?.email}</span>
            </span>
            <button type="button" className="admin-btn" onClick={logout}>
              退出
            </button>
          </div>
        </header>
        <main className={wide ? "main-tool" : "main-page"}>{children}</main>
      </div>
      {ledgerOpen && (
        <LedgerModal
          unit={me?.balance_unit || "积分"}
          entries={ledger}
          error={ledgerError}
          onClose={() => setLedgerOpen(false)}
        />
      )}
    </div>
  );
}

function Private({
  children,
  layout = "page",
}: {
  children: ReactNode;
  layout?: "page" | "canvas" | "tool";
}) {
  const { me, loading } = useAuth();
  if (loading) return <div className="center">加载中…</div>;
  if (!me) return <Navigate to="/login" replace />;
  if (layout === "canvas") return <>{children}</>;
  return <Shell wide={layout === "tool"}>{children}</Shell>;
}

export default function App() {
  const showAdmin = useShowAdmin();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <Private>
            <WorkspacePage />
          </Private>
        }
      />
      <Route
        path="/templates"
        element={
          <Private>
            <TemplatesPage />
          </Private>
        }
      />
      <Route
        path="/characters"
        element={
          <Private>
            <CharactersPage />
          </Private>
        }
      />
      <Route
        path="/workflow/:workflowId"
        element={
          <Private layout="canvas">
            <WorkflowCanvasPage />
          </Private>
        }
      />
      <Route path="/workflow" element={<Navigate to="/" replace />} />
      <Route path="/workflow/stage" element={<Navigate to="/" replace />} />
      <Route path="/workflow/board" element={<Navigate to="/" replace />} />
      <Route path="/workflow/legacy" element={<Navigate to="/" replace />} />
      <Route path="/showcase" element={<Navigate to="/templates" replace />} />
      <Route path="/history" element={<Navigate to="/" replace />} />
      <Route
        path="/studio"
        element={
          <Private layout="tool">
            <StudioPage />
          </Private>
        }
      />
      <Route
        path="/admin"
        element={
          showAdmin ? (
            <Private>
              <AdminPage />
            </Private>
          ) : (
            <Navigate to="/" replace />
          )
        }
      />
    </Routes>
  );
}
