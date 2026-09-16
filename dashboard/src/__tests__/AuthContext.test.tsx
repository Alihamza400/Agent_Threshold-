import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider, useAuth, hasRole } from "../auth/AuthContext";
import type { CurrentUser } from "../api/types";

vi.mock("../api/client", () => ({
  api: {
    login: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
  },
  saveOrg: vi.fn(),
  clearOrg: vi.fn(),
}));

import { api, saveOrg, clearOrg } from "../api/client";
const mockedApi = vi.mocked(api);
const mockedSaveOrg = vi.mocked(saveOrg);
const mockedClearOrg = vi.mocked(clearOrg);

function makeUser(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: "u1",
    org_id: "org1",
    email: "admin@test.com",
    role: "admin",
    is_active: true,
    ...overrides,
  };
}

function createQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}

function renderAuth(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>
  );
}

function TestConsumer() {
  const { user, ready, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="ready">{String(ready)}</span>
      <span data-testid="user">{user ? user.email : "null"}</span>
      <span data-testid="role">{user ? user.role : "none"}</span>
      <button onClick={() => login("a@b.com", "pw")}>login</button>
      <button onClick={logout}>logout</button>
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("AuthContext", () => {
  it("sets user after successful /me on mount", async () => {
    mockedApi.me.mockResolvedValueOnce(makeUser());

    renderAuth(<AuthProvider><TestConsumer /></AuthProvider>);

    await waitFor(() => {
      expect(screen.getByTestId("ready")).toHaveTextContent("true");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("admin@test.com");
    expect(screen.getByTestId("role")).toHaveTextContent("admin");
  });

  it("clears user when /me fails", async () => {
    mockedApi.me.mockRejectedValueOnce(new Error("unauthorized"));

    renderAuth(<AuthProvider><TestConsumer /></AuthProvider>);

    await waitFor(() => {
      expect(screen.getByTestId("ready")).toHaveTextContent("true");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("null");
    expect(mockedClearOrg).toHaveBeenCalled();
  });

  it("login calls api.login then api.me", async () => {
    mockedApi.me.mockResolvedValueOnce(makeUser());
    renderAuth(<AuthProvider><TestConsumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("ready")).toHaveTextContent("true"));

    const user = userEvent.setup();
    mockedApi.login.mockResolvedValueOnce({ access_token: "", refresh_token: "", token_type: "", expires_in: 0 });
    mockedApi.me.mockResolvedValueOnce(makeUser());

    await user.click(screen.getByText("login"));

    await waitFor(() => {
      expect(mockedApi.login).toHaveBeenCalledWith("a@b.com", "pw");
      expect(mockedApi.me).toHaveBeenCalledTimes(2);
      expect(mockedSaveOrg).toHaveBeenCalledWith("org1");
    });
  });

  it("logout clears user and calls api.logout", async () => {
    mockedApi.me.mockResolvedValueOnce(makeUser());
    renderAuth(<AuthProvider><TestConsumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("admin@test.com"));

    const user = userEvent.setup();
    mockedApi.logout.mockResolvedValueOnce(undefined);

    await user.click(screen.getByText("logout"));

    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("null");
    });
    expect(mockedClearOrg).toHaveBeenCalled();
  });

  it("logout handles api.logout failure gracefully", async () => {
    mockedApi.me.mockResolvedValueOnce(makeUser());
    renderAuth(<AuthProvider><TestConsumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("admin@test.com"));

    const user = userEvent.setup();
    mockedApi.logout.mockRejectedValueOnce(new Error("network error"));

    await user.click(screen.getByText("logout"));

    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("null");
    });
  });
});

describe("hasRole", () => {
  it("returns true when user has matching role", () => {
    expect(hasRole(makeUser({ role: "admin" }), ["admin", "approver"])).toBe(true);
  });

  it("returns false when user has no matching role", () => {
    expect(hasRole(makeUser({ role: "auditor" }), ["admin"])).toBe(false);
  });

  it("returns false when user is null", () => {
    expect(hasRole(null, ["admin"])).toBe(false);
  });
});
