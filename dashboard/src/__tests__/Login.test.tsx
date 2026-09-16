import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { Login } from "../pages/Login";
import { AuthProvider } from "../auth/AuthContext";

vi.mock("../api/client", () => ({
  api: {
    login: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
  },
  saveOrg: vi.fn(),
  clearOrg: vi.fn(),
}));

import { api, saveOrg } from "../api/client";
const mockedLogin = vi.mocked(api.login);
const mockedMe = vi.mocked(api.me);
const mockedSaveOrg = vi.mocked(saveOrg);

function mockAuthUser() {
  return { id: "u1", org_id: "org1", email: "admin@test.com", role: "admin" as const, is_active: true };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedMe.mockResolvedValue(mockAuthUser());
});

function renderLogin(initialEntries: string[] = ["/login"]) {
  return renderWithProviders(
    <AuthProvider><Login /></AuthProvider>,
    { initialEntries }
  );
}

describe("Login page", () => {
  it("renders the login form", async () => {
    renderLogin();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /agentthreshold/i })).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("shows error on failed login", async () => {
    const user = userEvent.setup();
    mockedLogin.mockRejectedValueOnce(new Error("Invalid credentials"));

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "bad@test.com");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
    });
  });

  it("redirects to home on successful login", async () => {
    const user = userEvent.setup();
    mockedLogin.mockResolvedValueOnce({ access_token: "a", refresh_token: "r", token_type: "bearer", expires_in: 3600 });
    mockedMe.mockResolvedValue(mockAuthUser());

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "admin@test.com");
    await user.type(screen.getByLabelText(/password/i), "pass123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockedLogin).toHaveBeenCalledWith("admin@test.com", "pass123");
    });
  });

  it("disables button while busy", async () => {
    const user = userEvent.setup();
    let resolveLogin!: () => void;
    mockedLogin.mockReturnValueOnce(new Promise((r) => { resolveLogin = () => r({ access_token: "", refresh_token: "", token_type: "", expires_in: 0 }); }));

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/password/i), "pw");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();
    });

    resolveLogin();
  });
});
