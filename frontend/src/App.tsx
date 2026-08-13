import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useState, type ReactNode } from "react";
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

const RAIL = [
  { to: "/", icon: "▦", label: "工作区", end: true },
  { to: "/templates", icon: "▤", label: "模板" },
  { to: "/characters", icon: "♙", label: "人物" },
] as const;

const TITLES: Record<string, string> = {
  "/": "我的项目",
  "/templates": "模板",
  "/characters": "人物",
  "/admin": "超管",
  "/studio": "工作室（暗门）",
};

function pageTitle(pathname: string) {
  if (TITLES[pathname]) return TITLES[pathname];
  if (pathname.startsWith("/workflow")) return "项目";
  return "SeeMeTVC";
}

function Shell({ children, wide }: { children: ReactNode; wide?: boolean }) {
  const { me, logout } = useAuth();
  const { pathname } = useLocation();
  const [accountOpen, setAccountOpen] = useState(false);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [ledger, setLedger] = useState<BalanceEntry[] | null>(null);
  const [ledgerError, setLedgerError] = useState("");

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

  return (
    <div
      className="app"
      onClick={() => setAccountOpen(false)}
    >
      <aside className="rail">
        <div className="logo" title="SeeMeTVC">
          ST
        </div>
        <nav>
          {RAIL.map((r) => (
            <NavLink key={r.to} to={r.to} end={r.to === "/"} title={r.label}>
              <span className="ico">{r.icon}</span>
              <span>{r.label}</span>
            </NavLink>
          ))}
          {me?.role === "super_admin" && (
            <NavLink to="/admin" title="超管">
              <span className="ico">⌘</span>
              <span>超管</span>
            </NavLink>
          )}
        </nav>
      </aside>
      <div className="shell">
        <header className="topbar">
          <div>
            <span className="eyebrow" style={{ margin: 0 }}>
              SeeMe<span>TVC</span>
            </span>
            <strong className="top-title">{pageTitle(pathname)}</strong>
          </div>
          <div className="top-actions">
            {me && (
              <button className="balance-chip" type="button" onClick={() => void openLedger()}>
                余额 <em>{me.balance.toFixed(2)}</em> {me.balance_unit}
              </button>
            )}
            <button
              className="account"
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setAccountOpen((v) => !v);
              }}
            >
              <span className="avatar">{initial}</span>
              <span>{me?.display_name || me?.email}</span>
            </button>
            {accountOpen && (
              <div className="account-menu">
                <button type="button" onClick={logout}>
                  退出
                </button>
              </div>
            )}
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
          <Private>
            <AdminPage />
          </Private>
        }
      />
    </Routes>
  );
}
