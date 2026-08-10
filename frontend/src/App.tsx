import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import AdminPage from "./pages/AdminPage";
import HistoryPage from "./pages/HistoryPage";
import LoginPage from "./pages/LoginPage";
import ShowcasePage from "./pages/ShowcasePage";
import StudioPage from "./pages/StudioPage";
import WorkflowPage from "./pages/WorkflowPage";

function Shell({
  children,
  layout = "page",
}: {
  children: React.ReactNode;
  layout?: "page" | "tool";
}) {
  const { me, logout } = useAuth();
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          SeeMe<span>TVC</span>
        </Link>
        <nav>
          <NavLink to="/" end>
            工作室
          </NavLink>
          <NavLink to="/workflow">工作流</NavLink>
          <NavLink to="/showcase">素材</NavLink>
          <NavLink to="/history">作品</NavLink>
          {me?.role === "super_admin" && <NavLink to="/admin">超管后台管理</NavLink>}
        </nav>
        <div className="topbar-right">
          {me && (
            <span className="balance-chip">
              余额 <em>{me.balance.toFixed(2)}</em> {me.balance_unit}
            </span>
          )}
          <button type="button" className="ghost" onClick={logout}>
            退出
          </button>
        </div>
      </header>
      <main className={layout === "tool" ? "main-tool" : "main-page"}>{children}</main>
    </div>
  );
}

function Private({
  children,
  layout = "page",
}: {
  children: React.ReactNode;
  layout?: "page" | "tool";
}) {
  const { me, loading } = useAuth();
  if (loading) return <div className="center">加载中…</div>;
  if (!me) return <Navigate to="/login" replace />;
  return <Shell layout={layout}>{children}</Shell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <Private layout="tool">
            <StudioPage />
          </Private>
        }
      />
      <Route
        path="/workflow"
        element={
          <Private layout="tool">
            <WorkflowPage />
          </Private>
        }
      />
      <Route
        path="/showcase"
        element={
          <Private>
            <ShowcasePage />
          </Private>
        }
      />
      <Route
        path="/history"
        element={
          <Private>
            <HistoryPage />
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
