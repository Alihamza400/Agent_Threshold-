import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, clearOrg, saveOrg } from "../api/client";
import type { CurrentUser } from "../api/types";

interface AuthContextValue {
  user: CurrentUser | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Try /auth/me — cookies are sent automatically.
    api
      .me()
      .then(setUser)
      .catch(() => clearOrg())
      .finally(() => setReady(true));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    await api.login(email, password);
    // Tokens are set as httpOnly cookies by the server.
    const me = await api.me();
    saveOrg(me.org_id);
    setUser(me);
  }, []);

  const logout = useCallback(() => {
    api.logout().catch(() => {});
    clearOrg();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function hasRole(user: CurrentUser | null, roles: string[]): boolean {
  return user !== null && roles.includes(user.role);
}