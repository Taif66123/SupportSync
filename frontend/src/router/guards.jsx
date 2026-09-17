import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../stores/auth.js";

export function RequireAuth() {
  const user = useAuth((s) => s.user);
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}

export function RequireRole({ role }) {
  const user = useAuth((s) => s.user);
  if (!user) return <Navigate to="/login" replace />;
  return user.role === role ? <Outlet /> : <Navigate to="/tickets" replace />;
}
