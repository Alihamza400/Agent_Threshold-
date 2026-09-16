import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/test-utils";
import { Dashboard } from "../pages/Dashboard";

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

const mockMetrics = {
  window_hours: 24,
  total_transactions_24h: 42,
  decision_mix: { approve: 30, reject: 10, escalate: 2 },
  fail_closed_rate: 0.1,
  latency_ms: { p50: 80, p95: 450 },
  daily_series: {
    days: ["2026-09-02", "2026-09-03", "2026-09-04"],
    counts: [10, 20, 12],
  },
  approvals: { pending: 3, resolved_24h: 8, avg_decision_hours: 1.5 },
};

const mockTransactions = [
  {
    id: "tx1",
    agent_id: "agent-abc-123",
    org_id: "org1",
    chain_id: "1",
    from_address: "0x" + "a".repeat(40),
    to_address: "0x" + "b".repeat(40),
    value_wei: 1000000,
    usd_value: 2.5,
    token: null,
    decision: "approve",
    confidence: 0.95,
    risk_summary: null,
    reasons: [],
    policy_version: 1,
    status: "completed",
    screened_ms: 120,
    created_at: "2026-09-16T10:00:00Z",
  },
];

const mockApprovals = [
  {
    id: "ap1",
    org_id: "org1",
    agent_id: "a1",
    agent_name: "bot",
    transaction_id: "tx1",
    chain_id: "1",
    from_address: "0x" + "a".repeat(40),
    to_address: "0x" + "b".repeat(40),
    value_wei: 5000,
    decision: "escalate",
    status: "pending",
    reasons: ["high value"],
    risk_summary: "unusual pattern",
    confidence: 0.6,
    expires_at: null,
    decided_by: null,
    decided_at: null,
    decision_note: null,
    created_at: "2026-09-16T10:00:00Z",
  },
];

const fakeFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fakeFetch);
  fakeFetch.mockImplementation((url: string) => {
    if (url.includes("/metrics/overview")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(mockMetrics) });
    }
    if (url.includes("/transactions")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(mockTransactions) });
    }
    if (url.includes("/approvals")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(mockApprovals) });
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Dashboard page", () => {
  it("renders dashboard heading", async () => {
    renderWithProviders(<Dashboard />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
    });
  });

  it("shows metrics cards with data after loading", async () => {
    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText("42")).toBeInTheDocument();
    });

    expect(screen.getByText("Screened (24h)")).toBeInTheDocument();
    expect(screen.getByText("p95 latency")).toBeInTheDocument();
    expect(screen.getByText("450 ms")).toBeInTheDocument();
    expect(screen.getByText("Fail-closed rate")).toBeInTheDocument();
    expect(screen.getByText("10.0%")).toBeInTheDocument();
    expect(screen.getByText("Pending approvals")).toBeInTheDocument();
  });

  it("renders recent decisions table with data", async () => {
    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText("120 ms")).toBeInTheDocument();
    });
  });

  it("renders decision mix chart section", async () => {
    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText("Decision mix (24h)")).toBeInTheDocument();
    });
  });

  it("shows empty state when no transactions", async () => {
    fakeFetch.mockImplementation((url: string) => {
      if (url.includes("/metrics/overview")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(mockMetrics) });
      }
      if (url.includes("/transactions")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
      }
      if (url.includes("/approvals")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    });

    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText("No transactions yet. Screen one via the SDK to see it here.")).toBeInTheDocument();
    });
  });

  it("renders screening volume section", async () => {
    renderWithProviders(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText(/Screening volume/)).toBeInTheDocument();
    });
  });
});
