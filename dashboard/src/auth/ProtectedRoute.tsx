import { Navigate, Outlet, useLocation } from "react-router-dom";
import { hasRole, useAuth } from "./AuthContext";

/**
 * Route guard. Server-side RBAC remains the source of truth (every endpoint
 * enforces roles); this only controls navigation/rendering for UX.
 */
export function ProtectedRoute({ roles }: { roles?: string[] }) {
  const { user, ready } = useAuth();
  const location = useLocation();

  if (!ready) return <div className="page-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  if (roles && !hasRole(user, roles)) return <Navigate to="/" replace />;
  return <Outlet />;
}