import { Link, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import AdminPage from "./pages/AdminPage";
import HistoryPage from "./pages/HistoryPage";
import LoginPage from "./pages/LoginPage";
import StudioPage from "./pages/StudioPage";

function Shell({ children }: { children: React.ReactNode }) {
  const { me, logout } = useAuth();
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          SeeMeTVC
        </Link>
        <nav>
          <Link to="/">工作室</Link>
          <Link to="/history">记录</Link>
          {me?.role === "super_admin" && <Link to="/admin">管理</Link>}
        </nav>
        <div className="topbar-right">
          {me && (
            <span className="balance-chip">
              余额 {me.balance.toFixed(2)} {me.balance_unit}
            </span>
          )}
          <button type="button" className="ghost" onClick={logout}>
            退出
          </button>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}

function Private({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <div className="center">加载中…</div>;
  if (!me) return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <Private>
            <StudioPage />
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
