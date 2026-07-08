import { NavLink, Route, Routes } from "react-router-dom";
import { Activity, BarChart3, ClipboardList, Cpu, LogOut, TriangleAlert } from "lucide-react";

import Dashboard from "./pages/Dashboard.jsx";
import Login from "./pages/Login.jsx";
import { useAuthStore } from "./state/authStore.js";

function PlaceholderPage({ title, description }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-8 shadow-panel">
      <p className="text-sm font-bold uppercase tracking-wide text-signal">Coming next</p>
      <h1 className="mt-2 text-2xl font-black text-ink">{title}</h1>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{description}</p>
    </section>
  );
}

function NavItem({ to, icon: Icon, children }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        [
          "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-bold transition",
          isActive
            ? "bg-white text-ink"
            : "text-slate-300 hover:bg-white/10 hover:text-white",
        ].join(" ")
      }
    >
      <Icon size={18} />
      {children}
    </NavLink>
  );
}

export default function App() {
  const { isAuthenticated, logout } = useAuthStore();

  if (!isAuthenticated) {
    return <Login />;
  }

  return (
    <div className="min-h-screen bg-field text-ink">
      <div className="grid min-h-screen grid-cols-[260px_minmax(0,1fr)] max-lg:grid-cols-1">
        <aside className="flex flex-col gap-8 bg-ink px-5 py-6 text-white">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-lg bg-emerald-100 text-sm font-black text-emerald-900">
              RV
            </span>
            <div>
              <strong className="block">Vision Console</strong>
              <span className="text-sm text-slate-400">Robot Logs</span>
            </div>
          </div>

          <nav className="grid gap-2">
            <NavItem to="/" icon={BarChart3}>Dashboard</NavItem>
            <NavItem to="/work-history" icon={ClipboardList}>Work History</NavItem>
            <NavItem to="/errors" icon={TriangleAlert}>Error Logs</NavItem>
            <NavItem to="/vision-align" icon={Activity}>Vision Align</NavItem>
          </nav>

          <div className="mt-auto rounded-lg border border-white/10 bg-white/5 p-4">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-200">
              <Cpu size={16} />
              Authenticated Session
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-400">
              JWT tokens are stored as HTTP-only cookies by the backend.
            </p>
            <button
              className="mt-4 inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-white px-3 text-sm font-black text-ink"
              onClick={logout}
              type="button"
            >
              <LogOut size={16} />
              Logout
            </button>
          </div>
        </aside>

        <main className="min-w-0 px-6 py-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route
              path="/work-history"
              element={<PlaceholderPage title="Work History" description="작업 이력 목록, 상세 로그, 상태 변경 화면을 독립 페이지로 확장할 자리입니다." />}
            />
            <Route
              path="/errors"
              element={<PlaceholderPage title="Error Logs" description="에러 로그 검색, 필터링, 생성 폼을 독립 페이지로 확장할 자리입니다." />}
            />
            <Route
              path="/vision-align"
              element={<PlaceholderPage title="Vision Align" description="카메라별 보정 offset 분석 화면을 독립 페이지로 확장할 자리입니다." />}
            />
          </Routes>
        </main>
      </div>
    </div>
  );
}
