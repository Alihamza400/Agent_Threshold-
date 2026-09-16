import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  AgentThresholdClient,
  unsignedTxToScreenRequest,
} from "../src/client.js";
import {
  ScreeningRejectedError,
  ScreeningEscalatedError,
  ScreeningUnavailableError,
  TransportError,
  UnauthorizedError,
} from "../src/errors.js";
import type { Decision, ScreenRequest } from "../src/schemas.js";

const BASE_URL = "http://screening.test";
const API_KEY = "at_test_key_000000000000000000000000000000000000";
const WALLET = "0x" + "1".repeat(40);
const COUNTERPARTY = "0x" + "2".repeat(40);

function approveBody(overrides: Partial<Decision> = {}): Decision {
  return {
    decision: "approve",
    reasons: [],
    confidence: 90.0,
    risk_summary: "within policy",
    policy_version: 1,
    transaction_id: "01approved",
    ...overrides,
  };
}

function makeRequest(overrides: Partial<ScreenRequest> = {}): ScreenRequest {
  return {
    agent_id: "01agent",
    chain_id: "base",
    from_address: WALLET,
    to_address: COUNTERPARTY,
    value_wei: 10 ** 16,
    calldata: null,
    gas_limit: null,
    gas_price_wei: null,
    token: null,
    task_context: null,
    ...overrides,
  };
}

function mockFetch(body: unknown, status = 200): void {
  const responseInit: ResponseInit = { status };
  const responseBody =
    status === 200 ? JSON.stringify(body) : String(body);
  const response = new Response(responseBody, responseInit);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
}

function mockFetchError(error: unknown): void {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(error);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("AgentThresholdClient", () => {
  describe("constructor", () => {
    it("requires baseUrl and apiKey", () => {
      expect(() => new AgentThresholdClient("", API_KEY)).toThrow(
        "baseUrl and apiKey are required",
      );
      expect(() => new AgentThresholdClient(BASE_URL, "")).toThrow(
        "baseUrl and apiKey are required",
      );
    });

    it("rejects negative maxRetries", () => {
      expect(
        () =>
          new AgentThresholdClient(BASE_URL, API_KEY, { maxRetries: -1 }),
      ).toThrow("maxRetries must be >= 0");
    });

    it("strips trailing slashes from baseUrl", () => {
      const client = new AgentThresholdClient(
        "http://test.com///",
        API_KEY,
      );
      expect(client).toBeDefined();
    });
  });

  describe("screen", () => {
    it("returns a Decision on success", async () => {
      mockFetch(approveBody());
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      const decision = await client.screen(makeRequest());
      expect(decision.decision).toBe("approve");
      expect(decision.transaction_id).toBe("01approved");
    });

    it("sends correct headers and body", async () => {
      mockFetch(approveBody());
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      const request = makeRequest();
      await client.screen(request);

      const call = vi.mocked(globalThis.fetch).mock.calls[0];
      expect(call[0]).toBe(`${BASE_URL}/v1/transactions/screen`);
      const init = call[1] as RequestInit;
      expect(init.method).toBe("POST");
      const headers = init.headers as Record<string, string>;
      expect(headers["X-API-Key"]).toBe(API_KEY);
      expect(headers["User-Agent"]).toBe("agentthreshold-sdk/0.1.0");
      const body = JSON.parse(String(init.body));
      expect(body.agent_id).toBe("01agent");
      expect(body.chain_id).toBe("base");
    });

    it("raises UnauthorizedError on 401", async () => {
      mockFetch("Invalid API key", 401);
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(client.screen(makeRequest())).rejects.toThrow(
        UnauthorizedError,
      );
    });

    it("raises ScreeningUnavailableError on 429", async () => {
      mockFetch("slow down", 429);
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(client.screen(makeRequest())).rejects.toThrow(
        ScreeningUnavailableError,
      );
    });

    it("raises ScreeningUnavailableError on 5xx", async () => {
      mockFetch("unavailable", 503);
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(client.screen(makeRequest())).rejects.toThrow(
        ScreeningUnavailableError,
      );
    });

    it("raises TransportError on unexpected status", async () => {
      mockFetch("bad request", 400);
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(client.screen(makeRequest())).rejects.toThrow(
        TransportError,
      );
    });

    it("raises ScreeningUnavailableError on malformed body", async () => {
      mockFetch({ decision: "not-a-decision" });
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(client.screen(makeRequest())).rejects.toThrow(
        ScreeningUnavailableError,
      );
    });

    it("raises TransportError on network failure (fail-closed)", async () => {
      mockFetchError(new TypeError("fetch failed"));
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(client.screen(makeRequest())).rejects.toThrow(
        TransportError,
      );
    });

    it("retries transport errors then succeeds", async () => {
      const successResponse = new Response(JSON.stringify(approveBody()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockRejectedValueOnce(new TypeError("fetch failed"))
        .mockResolvedValueOnce(successResponse);

      const client = new AgentThresholdClient(BASE_URL, API_KEY, {
        maxRetries: 1,
      });
      const decision = await client.screen(makeRequest());
      expect(decision.decision).toBe("approve");
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it("does not retry non-transport errors", async () => {
      mockFetch("Unauthorized", 401);
      const client = new AgentThresholdClient(BASE_URL, API_KEY, {
        maxRetries: 3,
      });
      await expect(client.screen(makeRequest())).rejects.toThrow(
        UnauthorizedError,
      );
      expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
    });

    it("throws after exhausting retries", async () => {
      mockFetchError(new TypeError("fetch failed"));
      const client = new AgentThresholdClient(BASE_URL, API_KEY, {
        maxRetries: 2,
      });
      await expect(client.screen(makeRequest())).rejects.toThrow(
        TransportError,
      );
      expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(3);
    });
  });

  describe("screenAndSign", () => {
    it("calls signer on APPROVE", async () => {
      mockFetch(approveBody());
      const signer = vi.fn().mockReturnValue({ signed: true });
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      const result = await client.screenAndSign(signer, {
        agentId: "01agent",
        chainId: "base",
        fromAddress: WALLET,
        toAddress: COUNTERPARTY,
        valueWei: 10 ** 16,
        taskContext: "pay supplier",
      });
      expect(signer).toHaveBeenCalledOnce();
      const unsignedTx = signer.mock.calls[0][0] as Record<string, unknown>;
      expect(unsignedTx.from).toBe(WALLET);
      expect(unsignedTx.value).toBe(10 ** 16);
      expect(result).toEqual({ signed: true });
    });

    it("does NOT call signer on REJECT", async () => {
      mockFetch(
        approveBody({
          decision: "reject",
          reasons: ["over limit"],
          confidence: 0.0,
        }),
      );
      const signer = vi.fn();
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(
        client.screenAndSign(signer, {
          agentId: "01agent",
          chainId: "base",
          fromAddress: WALLET,
          toAddress: COUNTERPARTY,
          valueWei: 10 ** 16,
        }),
      ).rejects.toThrow(ScreeningRejectedError);
      expect(signer).not.toHaveBeenCalled();
    });

    it("does NOT call signer on ESCALATE", async () => {
      mockFetch(
        approveBody({
          decision: "escalate",
          reasons: ["new counterparty"],
          confidence: 45.0,
        }),
      );
      const signer = vi.fn();
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(
        client.screenAndSign(signer, {
          agentId: "01agent",
          chainId: "base",
          fromAddress: WALLET,
          toAddress: COUNTERPARTY,
          valueWei: 10 ** 16,
        }),
      ).rejects.toThrow(ScreeningEscalatedError);
      expect(signer).not.toHaveBeenCalled();
    });

    it("does NOT call signer on transport failure", async () => {
      mockFetchError(new TypeError("fetch failed"));
      const signer = vi.fn();
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(
        client.screenAndSign(signer, {
          agentId: "01agent",
          chainId: "base",
          fromAddress: WALLET,
          toAddress: COUNTERPARTY,
          valueWei: 10 ** 16,
        }),
      ).rejects.toThrow(TransportError);
      expect(signer).not.toHaveBeenCalled();
    });

    it("does NOT call signer on 5xx", async () => {
      mockFetch("unavailable", 503);
      const signer = vi.fn();
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await expect(
        client.screenAndSign(signer, {
          agentId: "01agent",
          chainId: "base",
          fromAddress: WALLET,
          toAddress: COUNTERPARTY,
          valueWei: 10 ** 16,
        }),
      ).rejects.toThrow(ScreeningUnavailableError);
      expect(signer).not.toHaveBeenCalled();
    });
  });

  describe("screenAndSignTx", () => {
    it("normalizes an unsigned EVM tx and calls signer on APPROVE", async () => {
      mockFetch(approveBody());
      const signer = vi.fn().mockReturnValue({ hash: "0xabc" });
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      await client.screenAndSignTx(
        signer,
        {
          from: WALLET,
          to: COUNTERPARTY,
          value: "0x" + (10 ** 16).toString(16),
          data: "0xdeadbeef",
          gas: "0x" + (21000).toString(16),
          gasPrice: "0x" + (10 ** 9).toString(16),
        },
        { agentId: "01agent", chainId: "base" },
      );
      expect(signer).toHaveBeenCalledOnce();

      // Verify the screening request was sent with normalized values
      const call = vi.mocked(globalThis.fetch).mock.calls[0];
      const init = call[1] as RequestInit;
      const body = JSON.parse(String(init.body));
      expect(body.value_wei).toBe(10 ** 16);
      expect(body.gas_limit).toBe(21000);
      expect(body.gas_price_wei).toBe(10 ** 9);
      expect(body.calldata).toBe("0xdeadbeef");
    });
  });

  describe("unsignedTxToScreenRequest", () => {
    it("converts an unsigned tx to a ScreenRequest", () => {
      const result = unsignedTxToScreenRequest(
        {
          from: WALLET,
          to: COUNTERPARTY,
          value: 10 ** 16,
        },
        { agentId: "agent-1", chainId: "base" },
      );
      expect(result.from_address).toBe(WALLET);
      expect(result.to_address).toBe(COUNTERPARTY);
      expect(result.value_wei).toBe(10 ** 16);
    });

    it("handles hex string values", () => {
      const result = unsignedTxToScreenRequest(
        {
          from: WALLET,
          value: "0x" + (10 ** 16).toString(16),
        },
        { agentId: "agent-1", chainId: "ethereum" },
      );
      expect(result.value_wei).toBe(10 ** 16);
    });

    it("throws on missing 'from'", () => {
      expect(() =>
        unsignedTxToScreenRequest(
          { value: 100 },
          { agentId: "agent-1", chainId: "base" },
        ),
      ).toThrow("missing required field 'from'");
    });

    it("throws on missing 'value'", () => {
      expect(() =>
        unsignedTxToScreenRequest(
          { from: WALLET },
          { agentId: "agent-1", chainId: "base" },
        ),
      ).toThrow("missing required field 'value'");
    });

    it("throws on bool value", () => {
      expect(() =>
        unsignedTxToScreenRequest(
          { from: WALLET, value: true },
          { agentId: "agent-1", chainId: "base" },
        ),
      ).toThrow("bool");
    });

    it("maps data to calldata", () => {
      const result = unsignedTxToScreenRequest(
        { from: WALLET, value: 0, data: "0xbeef" },
        { agentId: "agent-1", chainId: "base" },
      );
      expect(result.calldata).toBe("0xbeef");
    });

    it("maps gas to gas_limit and gasPrice to gas_price_wei", () => {
      const result = unsignedTxToScreenRequest(
        {
          from: WALLET,
          value: 0,
          gas: 21000,
          gasPrice: 10 ** 9,
        },
        { agentId: "agent-1", chainId: "base" },
      );
      expect(result.gas_limit).toBe(21000);
      expect(result.gas_price_wei).toBe(10 ** 9);
    });
  });

  describe("close", () => {
    it("marks client as closed", () => {
      const client = new AgentThresholdClient(BASE_URL, API_KEY);
      client.close();
      expect(() => client.screen(makeRequest())).rejects.toThrow(
        "client is closed",
      );
    });
  });
});
