import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { Layout } from "./components/Layout";
import { Agents } from "./pages/Agents";
import { Approvals } from "./pages/Approvals";
import { AuditLog } from "./pages/AuditLog";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Policies } from "./pages/Policies";
import { Transactions } from "./pages/Transactions";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />

            <Route path="agents">
              <Route element={<ProtectedRoute roles={["admin"]} />}>
                <Route index element={<Agents />} />
              </Route>
            </Route>

            <Route path="policies">
              <Route element={<ProtectedRoute roles={["admin", "auditor"]} />}>
                <Route index element={<Policies />} />
              </Route>
            </Route>

            <Route path="approvals">
              <Route element={<ProtectedRoute roles={["admin", "approver"]} />}>
                <Route index element={<Approvals />} />
              </Route>
            </Route>

            <Route path="transactions">
              <Route element={<ProtectedRoute roles={["admin", "approver", "auditor"]} />}>
                <Route index element={<Transactions />} />
              </Route>
            </Route>

            <Route path="audit">
              <Route element={<ProtectedRoute roles={["admin", "approver", "auditor"]} />}>
                <Route index element={<AuditLog />} />
              </Route>
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}