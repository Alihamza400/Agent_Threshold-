import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "../test/test-utils";
import { Policies } from "../pages/Policies";

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

import * as client from "../api/client";

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
];

const mockPolicy = {
  agent_id: "a1",
  version: 3,
  spend_limit_usd: 1000,
  daily_spend_limit_usd: 5000,
  allow_list: [] as string[],
  deny_list: [] as string[],
  rate_limit_per_minute: 10,
  active_from_minute: 0,
  active_to_minute: 1440,
  gas_ceiling: 100000,
  anomaly_threshold: 80,
  is_active: true,
  created_by: "u1",
  created_at: "2026-09-10T00:00:00Z",
};

const mockVersions = [
  { ...mockPolicy, version: 3, is_active: true },
  { ...mockPolicy, version: 2, is_active: false },
];

const mockAuditChanges = {
  items: [
    {
      id: "r1",
      org_id: "org1",
      agent_id: "a1",
      event_type: "policy_update",
      event_hash: "abc",
      details: {
        actor_email: "admin@test.com",
        from_version: 2,
        to_version: 3,
        change_note: "raised threshold",
      },
      anchored_batch_id: 1,
      created_at: "2026-09-10T00:00:00Z",
    },
  ],
  total: 1,
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(client.api, "listAgents").mockResolvedValue(mockAgents);
  vi.spyOn(client.api, "getPolicy").mockResolvedValue(mockPolicy);
  vi.spyOn(client.api, "listPolicyVersions").mockResolvedValue(mockVersions);
  vi.spyOn(client.api, "searchAudit").mockResolvedValue(mockAuditChanges);
});

describe("Policies page", () => {
  it("renders policies heading", async () => {
    renderWithProviders(<Policies />);
    expect(screen.getByRole("heading", { name: /policies/i })).toBeInTheDocument();
  });

  it("shows agent selector with options", async () => {
    renderWithProviders(<Policies />);
    await waitFor(() => {
      expect(screen.getByText(/Payment Bot/)).toBeInTheDocument();
    });
  });

  it("displays policy heading after selecting agent", async () => {
    renderWithProviders(<Policies />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Active policy/ })).toBeInTheDocument();
    });
  });

  it("shows version history", async () => {
    renderWithProviders(<Policies />);
    await waitFor(() => {
      expect(screen.getByText("Version history")).toBeInTheDocument();
    });
  });

  it("shows recent policy changes", async () => {
    renderWithProviders(<Policies />);
    await waitFor(() => {
      expect(screen.getByText("raised threshold")).toBeInTheDocument();
    });
  });

  it("allows editing and submitting policy update", async () => {
    vi.spyOn(client.api, "updatePolicy").mockResolvedValueOnce({ ...mockPolicy, version: 4 });

    renderWithProviders(<Policies />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Active policy/ })).toBeInTheDocument();
    });

    const spendInput = screen.getByLabelText(/per-tx spend limit/i);
    const user = { clear: async () => { fireEvent.change(spendInput, { target: { value: "" } }); }, type: async (el: HTMLElement, text: string) => { fireEvent.change(el, { target: { value: text } }); } };
    fireEvent.change(spendInput, { target: { value: "2000" } });
    fireEvent.change(screen.getByLabelText(/change note/i), { target: { value: "increased limit" } });

    const form = spendInput.closest("form")!;
    fireEvent.submit(form);

    await waitFor(() => {
      expect(client.api.updatePolicy).toHaveBeenCalledWith("a1", expect.objectContaining({
        spend_limit_usd: 2000,
        change_note: "increased limit",
      }));
    });
  });

  it("shows success message after policy update", async () => {
    vi.spyOn(client.api, "updatePolicy").mockResolvedValueOnce({ ...mockPolicy, version: 4 });

    renderWithProviders(<Policies />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Active policy/ })).toBeInTheDocument();
    });

    const form = screen.getByRole("button", { name: /publish new version/i }).closest("form")!;
    fireEvent.submit(form);

    await waitFor(() => {
      expect(screen.getByText(/Published version 4/)).toBeInTheDocument();
    });
  });

  it("shows error message on failed policy update", async () => {
    vi.spyOn(client.api, "updatePolicy").mockRejectedValueOnce(new Error("conflict: stale version"));

    renderWithProviders(<Policies />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Active policy/ })).toBeInTheDocument();
    });

    const form = screen.getByRole("button", { name: /publish new version/i }).closest("form")!;
    fireEvent.submit(form);

    await waitFor(() => {
      expect(screen.getByText(/conflict: stale version/)).toBeInTheDocument();
    });
  });
});
