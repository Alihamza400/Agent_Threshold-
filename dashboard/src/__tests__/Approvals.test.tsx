import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { Approvals } from "../pages/Approvals";

vi.mock("../api/client", () => ({
  api: {
    listApprovals: vi.fn(),
    decideApproval: vi.fn(),
  },
}));

import { api } from "../api/client";
const mockedApi = vi.mocked(api);

const mockPendingApprovals = [
  {
    id: "ap1",
    org_id: "org1",
    agent_id: "a1",
    agent_name: "Payment Bot",
    transaction_id: "tx1",
    chain_id: "1",
    from_address: "0x" + "a".repeat(40),
    to_address: "0x" + "b".repeat(40),
    value_wei: 5000000,
    decision: "escalate",
    status: "pending",
    reasons: ["high value"],
    risk_summary: "unusual pattern detected",
    confidence: 0.6,
    expires_at: null,
    decided_by: null,
    decided_at: null,
    decision_note: null,
    created_at: "2026-09-16T10:00:00Z",
  },
  {
    id: "ap2",
    org_id: "org1",
    agent_id: "a2",
    agent_name: "Swap Bot",
    transaction_id: "tx2",
    chain_id: "1",
    from_address: "0x" + "c".repeat(40),
    to_address: "0x" + "d".repeat(40),
    value_wei: 1000000,
    decision: "escalate",
    status: "pending",
    reasons: ["unknown recipient"],
    risk_summary: null,
    confidence: 0.4,
    expires_at: null,
    decided_by: null,
    decided_at: null,
    decision_note: null,
    created_at: "2026-09-16T11:00:00Z",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.listApprovals.mockResolvedValue(mockPendingApprovals);
});

describe("Approvals page", () => {
  it("renders approval queue heading", async () => {
    renderWithProviders(<Approvals />);

    expect(screen.getByRole("heading", { name: /approval queue/i })).toBeInTheDocument();
  });

  it("renders tab buttons", async () => {
    renderWithProviders(<Approvals />);

    expect(screen.getByRole("button", { name: /pending/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approved/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rejected/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expired/ })).toBeInTheDocument();
  });

  it("shows pending count in tab", async () => {
    renderWithProviders(<Approvals />);

    await waitFor(() => {
      expect(screen.getByText(/pending \(2\)/)).toBeInTheDocument();
    });
  });

  it("displays approval items", async () => {
    renderWithProviders(<Approvals />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    expect(screen.getByText("Swap Bot")).toBeInTheDocument();
    expect(screen.getByText("5,000,000")).toBeInTheDocument();
  });

  it("shows approve and reject buttons for pending items", async () => {
    renderWithProviders(<Approvals />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    const approveButtons = screen.getAllByRole("button", { name: /approve$/i });
    const rejectButtons = screen.getAllByRole("button", { name: /reject$/i });
    expect(approveButtons.length).toBe(2);
    expect(rejectButtons.length).toBe(2);
  });

  it("sends approve action for first item", async () => {
    const user = userEvent.setup();
    mockedApi.decideApproval.mockResolvedValueOnce({
      id: "ap1",
      status: "approved",
      decided_at: "2026-09-16T12:00:00Z",
      decided_by: "u1",
      decision_note: "looks safe",
    } as any);

    renderWithProviders(<Approvals />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    const approveButtons = screen.getAllByRole("button", { name: /approve$/i });
    await user.click(approveButtons[0]);

    await waitFor(() => {
      expect(mockedApi.decideApproval).toHaveBeenCalledWith("ap1", "approve", "");
    });
  });

  it("sends reject action for first item", async () => {
    const user = userEvent.setup();
    mockedApi.decideApproval.mockResolvedValueOnce({
      id: "ap1",
      status: "rejected",
      decided_at: "2026-09-16T12:00:00Z",
      decided_by: "u1",
    } as any);

    renderWithProviders(<Approvals />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    const rejectButtons = screen.getAllByRole("button", { name: /reject$/i });
    await user.click(rejectButtons[0]);

    await waitFor(() => {
      expect(mockedApi.decideApproval).toHaveBeenCalledWith("ap1", "reject", "");
    });
  });

  it("shows empty state when no approvals", async () => {
    mockedApi.listApprovals.mockResolvedValueOnce([]);

    renderWithProviders(<Approvals />);

    await waitFor(() => {
      expect(screen.getByText("Nothing in this queue.")).toBeInTheDocument();
    });
  });

  it("switches tabs and fetches different data", async () => {
    const user = userEvent.setup();
    const approved = [
      { ...mockPendingApprovals[0], id: "ap-approved", status: "approved" },
    ];
    mockedApi.listApprovals.mockResolvedValueOnce(approved);

    renderWithProviders(<Approvals />);

    await waitFor(() => {
      expect(screen.getByText("Payment Bot")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /approved/ }));

    await waitFor(() => {
      expect(mockedApi.listApprovals).toHaveBeenCalledWith("approved");
    });
  });
});
