import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const NAV = [
  { to: "/", label: "Dashboard", roles: ["admin", "approver", "auditor"] },
  { to: "/agents", label: "Agents", roles: ["admin"] },
  { to: "/policies", label: "Policies", roles: ["admin", "auditor"] },
  { to: "/approvals", label: "Approvals", roles: ["admin", "approver"] },
  { to: "/transactions", label: "Transactions", roles: ["admin", "approver", "auditor"] },
  { to: "/audit", label: "Audit Log", roles: ["admin", "approver", "auditor"] },
];

export function Layout() {
  const { user, logout } = useAuth();
  const visible = NAV.filter((n) => !user || n.roles.includes(user.role));

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">AgentThreshold</div>
        <nav>
          {visible.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
              end={n.to === "/"}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="role-badge">{user?.role}</span>
          <span className="user-email">{user?.email}</span>
          <button className="btn btn-ghost" onClick={logout}>
            Sign out
          </button>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}