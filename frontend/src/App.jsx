import { useEffect } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./stores/auth.js";
import { useNotifications } from "./stores/notifications.js";
import { RequireAuth, RequireRole } from "./router/guards.jsx";
import { roleLabel } from "./plugins/format.js";
import { Toasts } from "./components/Toasts.jsx";
import Login from "./views/Login.jsx";
import Tickets from "./views/Tickets.jsx";
import TicketDetail from "./views/TicketDetail.jsx";
import AdminUsers from "./views/AdminUsers.jsx";

function Header() {
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  if (!user) return null;
  return (
    <header className="topbar">
      <Link to="/tickets" className="brand">SupportSync</Link>
      <nav>
        <Link to="/tickets">Tickets</Link>
        {user.role === "admin" && <Link to="/admin/users">Users</Link>}
      </nav>
      <div className="topbar-user">
        <span>{user.full_name} · {roleLabel(user.role)}</span>
        <button className="btn btn-ghost" onClick={logout}>Log out</button>
      </div>
    </header>
  );
}

export default function App() {
  const accessToken = useAuth((s) => s.accessToken);
  const connect = useNotifications((s) => s.connect);
  const disconnect = useNotifications((s) => s.disconnect);

  // One live-notification connection per logged-in session.
  useEffect(() => {
    if (accessToken) connect(accessToken);
    else disconnect();
    return disconnect;
  }, [accessToken, connect, disconnect]);

  return (
    <BrowserRouter>
      <Header />
      <Toasts />
      <main className="page">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth />}>
            <Route path="/tickets" element={<Tickets />} />
            <Route path="/tickets/:id" element={<TicketDetail />} />
            <Route element={<RequireRole role="admin" />}>
              <Route path="/admin/users" element={<AdminUsers />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/tickets" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
