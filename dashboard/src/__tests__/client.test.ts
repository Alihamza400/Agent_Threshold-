import { describe, it, expect, beforeEach, vi } from "vitest";
import { api, ApiError, saveOrg, clearOrg, downloadAuditExport } from "../api/client";

const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: new Headers({ "content-type": "application/json" }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(typeof data === "string" ? data : JSON.stringify(data)),
    blob: () => Promise.resolve(new Blob([JSON.stringify(data)])),
    redirected: false,
    type: "basic",
    url: "",
    body: null,
    bodyUsed: false,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    clone: () => jsonResponse(data, status),
    bytes: () => Promise.resolve(new Uint8Array()),
  } as unknown as Response;
}

function errorJsonResponse(status: number, detail: string): Response {
  return {
    ok: false,
    status,
    statusText: "Error",
    headers: new Headers({ "content-type": "application/json" }),
    json: () => Promise.resolve({ detail }),
    text: () => Promise.resolve(JSON.stringify({ detail })),
    blob: () => Promise.resolve(new Blob()),
    redirected: false,
    type: "basic",
    url: "",
    body: null,
    bodyUsed: false,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    clone: () => errorJsonResponse(status, detail),
    bytes: () => Promise.resolve(new Uint8Array()),
  } as unknown as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe("localStorage helpers", () => {
  it("saveOrg stores org id", () => {
    saveOrg("org-123");
    expect(localStorage.getItem("at_org_id")).toBe("org-123");
  });

  it("clearOrg removes org id", () => {
    localStorage.setItem("at_org_id", "org-123");
    clearOrg();
    expect(localStorage.getItem("at_org_id")).toBeNull();
  });
});

describe("ApiError", () => {
  it("creates error with status and detail", () => {
    const err = new ApiError(404, "not found");
    expect(err).toBeInstanceOf(Error);
    expect(err.status).toBe(404);
    expect(err.detail).toBe("not found");
    expect(err.message).toBe("not found");
  });
});

describe("api.login", () => {
  it("sends POST with email and password", async () => {
    const tokenResp = { access_token: "abc", refresh_token: "xyz", token_type: "bearer", expires_in: 3600 };
    mockFetch.mockResolvedValueOnce(jsonResponse(tokenResp));

    const result = await api.login("user@test.com", "pass123");

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe("/v1/auth/login");
    expect(opts.method).toBe("POST");
    expect(opts.credentials).toBe("include");
    const body = JSON.parse(opts.body);
    expect(body.email).toBe("user@test.com");
    expect(body.password).toBe("pass123");
    expect(result).toEqual(tokenResp);
  });

  it("throws ApiError on failure", async () => {
    mockFetch.mockResolvedValueOnce(errorJsonResponse(401, "invalid credentials"));

    try {
      await api.login("x@x.com", "bad");
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(401);
      expect((e as ApiError).detail).toBe("invalid credentials");
    }
  });
});

describe("api.me", () => {
  it("fetches current user", async () => {
    const me = { id: "u1", org_id: "org1", email: "admin@test.com", role: "admin", is_active: true };
    mockFetch.mockResolvedValueOnce(jsonResponse(me));

    const result = await api.me();

    expect(mockFetch).toHaveBeenCalledOnce();
    expect(mockFetch.mock.calls[0][0]).toBe("/v1/auth/me");
    expect(result).toEqual(me);
  });
});

describe("api.logout", () => {
  it("sends POST to /auth/logout", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 204, statusText: "No Content" } as unknown as Response);

    await api.logout();

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe("/v1/auth/logout");
    expect(opts.method).toBe("POST");
  });
});

describe("api.listAgents", () => {
  it("fetches agents list", async () => {
    const agents = [{ id: "a1", name: "bot", wallet_address: "0x" + "1".repeat(40), status: "active", halted: false }];
    mockFetch.mockResolvedValueOnce(jsonResponse(agents));

    const result = await api.listAgents();

    expect(result).toEqual(agents);
    expect(mockFetch.mock.calls[0][0]).toBe("/v1/agents");
  });
});

describe("api.registerAgent", () => {
  it("sends POST with name and wallet", async () => {
    const registered = { agent: { id: "a2", name: "new" }, default_policy_id: null };
    mockFetch.mockResolvedValueOnce(jsonResponse(registered));

    const result = await api.registerAgent("new", "0x" + "a".repeat(40));

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe("/v1/agents/register");
    expect(opts.method).toBe("POST");
    const body = JSON.parse(opts.body);
    expect(body.name).toBe("new");
    expect(body.wallet_address).toBe("0x" + "a".repeat(40));
    expect(result).toEqual(registered);
  });
});

describe("api.getPolicy", () => {
  it("fetches policy for agent", async () => {
    const policy = { agent_id: "a1", version: 1, anomaly_threshold: 80, is_active: true };
    mockFetch.mockResolvedValueOnce(jsonResponse(policy));

    const result = await api.getPolicy("a1");

    expect(mockFetch.mock.calls[0][0]).toBe("/v1/agents/a1/policy");
    expect(result).toEqual(policy);
  });
});

describe("api.updatePolicy", () => {
  it("sends PUT with policy update", async () => {
    const updated = { agent_id: "a1", version: 2, anomaly_threshold: 90 };
    mockFetch.mockResolvedValueOnce(jsonResponse(updated));

    const result = await api.updatePolicy("a1", { anomaly_threshold: 90, change_note: "raised" });

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe("/v1/agents/a1/policy");
    expect(opts.method).toBe("PUT");
    expect(JSON.parse(opts.body)).toEqual({ anomaly_threshold: 90, change_note: "raised" });
    expect(result).toEqual(updated);
  });
});

describe("api.listApprovals", () => {
  it("sends status query param", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse([]));

    await api.listApprovals("approved");

    expect(mockFetch.mock.calls[0][0]).toBe("/v1/approvals?status=approved");
  });

  it("includes agent_id when provided", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse([]));

    await api.listApprovals("pending", "agent-1");

    expect(mockFetch.mock.calls[0][0]).toBe("/v1/approvals?status=pending&agent_id=agent-1");
  });
});

describe("api.decideApproval", () => {
  it("sends POST with action", async () => {
    const approval = { id: "ap1", status: "approved" };
    mockFetch.mockResolvedValueOnce(jsonResponse(approval));

    const result = await api.decideApproval("ap1", "approve", "looks good");

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe("/v1/approvals/ap1/approve");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ note: "looks good" });
    expect(result).toEqual(approval);
  });

  it("defaults note to null", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    await api.decideApproval("ap2", "reject");

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.note).toBeNull();
  });
});

describe("api.searchAudit", () => {
  it("builds query string from params", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    await api.searchAudit({ eventType: "decision", limit: 10 });

    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("event_type=decision");
    expect(url).toContain("limit=10");
  });
});

describe("api.listTransactions", () => {
  it("builds query string with filters", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse([]));

    await api.listTransactions({ agentId: "a1", decision: "reject", limit: 25 });

    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("agent_id=a1");
    expect(url).toContain("decision=reject");
    expect(url).toContain("limit=25");
  });
});

describe("api.metricsOverview", () => {
  it("fetches metrics", async () => {
    const metrics = {
      window_hours: 24,
      total_transactions_24h: 100,
      decision_mix: { approve: 70, reject: 20, escalate: 10 },
      fail_closed_rate: 0.2,
      latency_ms: { p50: 100, p95: 500 },
      daily_series: { days: [], counts: [] },
      approvals: { pending: 3, resolved_24h: 10, avg_decision_hours: 2 },
    };
    mockFetch.mockResolvedValueOnce(jsonResponse(metrics));

    const result = await api.metricsOverview();

    expect(mockFetch.mock.calls[0][0]).toBe("/v1/metrics/overview");
    expect(result.total_transactions_24h).toBe(100);
  });
});

describe("api.killSwitch", () => {
  it("sends POST with scope and reason", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    await api.killSwitch("agent", "a1", "compromised");

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe("/v1/kill-switch");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ scope: "agent", agent_id: "a1", reason: "compromised" });
  });
});

describe("api.resumeKillSwitch", () => {
  it("sends DELETE with scope", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    await api.resumeKillSwitch("org");

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe("/v1/kill-switch?scope=org");
    expect(opts.method).toBe("DELETE");
  });
});

describe("org header", () => {
  it("includes x-org-id header when set in localStorage", async () => {
    localStorage.setItem("at_org_id", "my-org");
    mockFetch.mockResolvedValueOnce(jsonResponse([]));

    await api.listAgents();

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers["x-org-id"]).toBe("my-org");
  });

  it("does not include x-org-id when not set", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse([]));

    await api.listAgents();

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers["x-org-id"]).toBeUndefined();
  });
});

describe("retry on 401", () => {
  it("retries after successful refresh", async () => {
    const data = { id: "u1" };
    mockFetch
      .mockResolvedValueOnce(errorJsonResponse(401, "unauthorized"))
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse(data));

    const result = await api.me();

    expect(mockFetch).toHaveBeenCalledTimes(3);
    expect(result).toEqual(data);
    expect(mockFetch.mock.calls[1][0]).toBe("/v1/auth/refresh");
  });

  it("throws after failed refresh", async () => {
    mockFetch
      .mockResolvedValueOnce(errorJsonResponse(401, "unauthorized"))
      .mockResolvedValueOnce(errorJsonResponse(401, "refresh failed"));

    await expect(api.me()).rejects.toThrow(ApiError);
  });
});

describe("downloadAuditExport", () => {
  it("creates and clicks a download link", () => {
    const clickSpy = vi.fn();
    const appendChildSpy = vi.spyOn(document.body, "appendChild").mockImplementation(() => {
      return {} as unknown as Node;
    });
    const removeSpy = vi.fn();
    const createElementSpy = vi.spyOn(document, "createElement").mockReturnValue({
      click: clickSpy,
      href: "",
      download: "",
      remove: removeSpy,
    } as unknown as HTMLAnchorElement);

    const origCreate = URL.createObjectURL;
    const origRevoke = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();

    downloadAuditExport("col1,col2\nval1,val2", "test.csv");

    expect(createElementSpy).toHaveBeenCalledWith("a");
    expect(clickSpy).toHaveBeenCalledOnce();
    expect(appendChildSpy).toHaveBeenCalledOnce();

    createElementSpy.mockRestore();
    appendChildSpy.mockRestore();
    URL.createObjectURL = origCreate;
    URL.revokeObjectURL = origRevoke;
  });
});
