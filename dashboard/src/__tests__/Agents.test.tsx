import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { Agents } from "../pages/Agents";

vi.mock("../api/client", () => ({
  api: {
    listAgents: vi.fn(),
    registerAgent: vi.fn(),
    killSwitch: vi.fn(),
    resumeKillSwitch: vi.fn(),
  },
}));

vi.mock("../auth/AuthContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../auth/AuthContext")>();
  return {
    ...actual,
    useAuth: () => ({
      user: { id: "u1", org_id: "org1", email: "admin@test.com", role: "admin" as const, is_active: true },
      ready: true,
      login: vi.fn(),
      logout: vi.fn(),
    }),
  };
});

import { api } from "../api/client";
const mockedApi = vi.mocked(api);

const mockAgents = [
  {
    id: "a1",
    org_id: "org1",
    name: "Payment Bot",
    wallet_address: "0x" + "1".repeat(40),
    status: "active" as const,
    halted: false,
    halt_reason: null,
    created_at: "2026-09-01T00:00:00Z",
  },
  {
    id: "a2",
    org_id: "org1",
    name: "Swap Bot",
    wallet_address: "0x" + "2".repeat(40),
    status: "active" as const,
    halted: true,
    halt_reason: "compromised key",
    created_at: "2026-09-02T00:00:00Z",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.listAgents.mockResolvedValue(mockAgents);
});

describe("Agents page", () => {
  it("renders agents heading and list", async () => {
    renderWithProviders(<Agents />);

    expect(screen.getByRole("heading", { name: /agents/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });
    expect(screen.getByText("Swap Bot")).toBeInTheDocument();
  });

  it("shows halted status correctly", async () => {
    renderWithProviders(<Agents />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    expect(screen.getByText("No")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.getByText("compromised key")).toBeInTheDocument();
  });

  it("shows empty state when no agents", async () => {
    mockedApi.listAgents.mockResolvedValueOnce([]);

    renderWithProviders(<Agents />);

    await waitFor(() => {
      expect(screen.getByText("No agents registered.")).toBeInTheDocument();
    });
  });

  it("renders register agent form", async () => {
    renderWithProviders(<Agents />);

    expect(screen.getByPlaceholderText("Agent name")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/0x wallet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /register$/i })).toBeInTheDocument();
  });

  it("submits register form", async () => {
    const user = userEvent.setup();
    mockedApi.registerAgent.mockResolvedValueOnce({
      agent: { ...mockAgents[0], id: "a3", name: "New Bot" },
      default_policy_id: null,
    });

    renderWithProviders(<Agents />);

    await user.type(screen.getByPlaceholderText("Agent name"), "New Bot");
    await user.type(screen.getByPlaceholderText(/0x wallet/i), "0x" + "3".repeat(40));
    await user.click(screen.getByRole("button", { name: /register$/i }));

    await waitFor(() => {
      expect(mockedApi.registerAgent).toHaveBeenCalledWith("New Bot", "0x" + "3".repeat(40));
    });
  });

  it("shows error on failed registration", async () => {
    const user = userEvent.setup();
    mockedApi.registerAgent.mockRejectedValueOnce(new Error("wallet already exists"));

    renderWithProviders(<Agents />);

    await user.type(screen.getByPlaceholderText("Agent name"), "Dup Bot");
    await user.type(screen.getByPlaceholderText(/0x wallet/i), "0x" + "4".repeat(40));
    await user.click(screen.getByRole("button", { name: /register$/i }));

    await waitFor(() => {
      expect(screen.getByText("wallet already exists")).toBeInTheDocument();
    });
  });

  it("shows resume button for halted agents", async () => {
    renderWithProviders(<Agents />);

    await waitFor(() => {
      expect(screen.getByText("Swap Bot")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /resume$/i })).toBeInTheDocument();
  });

  it("opens halt confirmation modal", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Agents />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    const haltButtons = screen.getAllByRole("button", { name: /halt$/i });
    await user.click(haltButtons[0]);

    expect(screen.getByRole("heading", { name: /confirm kill-switch/i })).toBeInTheDocument();
    expect(screen.getByText(/This halts "Payment Bot"/)).toBeInTheDocument();
  });

  it("shows org halt button for admin", async () => {
    renderWithProviders(<Agents />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /halt entire org/i })).toBeInTheDocument();
  });

  it("sends kill-switch on confirm", async () => {
    const user = userEvent.setup();
    mockedApi.killSwitch.mockResolvedValueOnce(undefined);

    renderWithProviders(<Agents />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    const haltButtons = screen.getAllByRole("button", { name: /halt$/i });
    await user.click(haltButtons[0]);

    await user.click(screen.getByRole("button", { name: /confirm halt/i }));

    await waitFor(() => {
      expect(mockedApi.killSwitch).toHaveBeenCalledWith("agent", "a1", "admin action");
    });
  });
});
