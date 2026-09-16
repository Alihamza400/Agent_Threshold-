import { describe, it, expect } from "vitest";
import {
  ChainIdSchema,
  DecisionTypeSchema,
  ScreenRequestSchema,
  DecisionSchema,
  parseScreenRequest,
  parseDecision,
} from "../src/schemas.js";

const VALID_SCREEN_REQUEST = {
  agent_id: "01abc",
  chain_id: "base",
  from_address: "0x1111111111111111111111111111111111111111",
  to_address: "0x2222222222222222222222222222222222222222",
  value_wei: 10 ** 16,
  calldata: null,
  gas_limit: 21000,
  gas_price_wei: 10 ** 9,
  token: null,
  task_context: "pay supplier",
};

const VALID_DECISION = {
  decision: "escalate",
  reasons: ["aggregate confidence 55.0 below escalate threshold 60.0"],
  confidence: 55.0,
  risk_summary: "new counterparty",
  policy_version: 3,
  transaction_id: "01xyz",
};

describe("ChainId", () => {
  it("accepts valid chain ids", () => {
    expect(ChainIdSchema.parse("ethereum")).toBe("ethereum");
    expect(ChainIdSchema.parse("base")).toBe("base");
    expect(ChainIdSchema.parse("arbitrum")).toBe("arbitrum");
  });

  it("rejects unknown chain ids", () => {
    expect(() => ChainIdSchema.parse("polygon")).toThrow();
    expect(() => ChainIdSchema.parse("")).toThrow();
  });
});

describe("DecisionType", () => {
  it("accepts valid decision types", () => {
    expect(DecisionTypeSchema.parse("approve")).toBe("approve");
    expect(DecisionTypeSchema.parse("reject")).toBe("reject");
    expect(DecisionTypeSchema.parse("escalate")).toBe("escalate");
  });

  it("rejects unknown decision types", () => {
    expect(() => DecisionTypeSchema.parse("unknown")).toThrow();
    expect(() => DecisionTypeSchema.parse("APPROVE")).toThrow();
  });
});

describe("ScreenRequest", () => {
  it("accepts a valid request", () => {
    const result = parseScreenRequest(VALID_SCREEN_REQUEST);
    expect(result.agent_id).toBe("01abc");
    expect(result.chain_id).toBe("base");
    expect(result.from_address).toBe("0x1111111111111111111111111111111111111111");
    expect(result.to_address).toBe("0x2222222222222222222222222222222222222222");
    expect(result.value_wei).toBe(10 ** 16);
  });

  it("lowercases addresses", () => {
    const result = parseScreenRequest({
      ...VALID_SCREEN_REQUEST,
      from_address: "0xAAAA111111111111111111111111111111111111",
    });
    expect(result.from_address).toBe("0xaaaa111111111111111111111111111111111111");
  });

  it("rejects invalid from_address", () => {
    expect(() =>
      parseScreenRequest({
        ...VALID_SCREEN_REQUEST,
        from_address: "0x123",
      }),
    ).toThrow();
  });

  it("rejects invalid to_address", () => {
    expect(() =>
      parseScreenRequest({
        ...VALID_SCREEN_REQUEST,
        to_address: "not-an-address",
      }),
    ).toThrow();
  });

  it("rejects negative value_wei", () => {
    expect(() =>
      parseScreenRequest({
        ...VALID_SCREEN_REQUEST,
        value_wei: -1,
      }),
    ).toThrow();
  });

  it("accepts null to_address (contract deploy)", () => {
    const result = parseScreenRequest({
      ...VALID_SCREEN_REQUEST,
      to_address: null,
    });
    expect(result.to_address).toBeNull();
  });

  it("accepts a minimal request", () => {
    const result = parseScreenRequest({
      agent_id: "agent-1",
      chain_id: "ethereum",
      from_address: "0x0000000000000000000000000000000000000001",
      value_wei: 0,
    });
    expect(result.agent_id).toBe("agent-1");
    expect(result.calldata).toBeNull();
    expect(result.gas_limit).toBeNull();
  });

  it("round-trips through JSON", () => {
    const request = parseScreenRequest(VALID_SCREEN_REQUEST);
    const json = JSON.stringify(request);
    const parsed = parseScreenRequest(JSON.parse(json));
    expect(parsed).toEqual(request);
  });

  it("rejects extra fields", () => {
    expect(() =>
      parseScreenRequest({
        ...VALID_SCREEN_REQUEST,
        unknown_field: "bad",
      }),
    ).toThrow();
  });

  it("enforces max_length on task_context", () => {
    expect(() =>
      parseScreenRequest({
        ...VALID_SCREEN_REQUEST,
        task_context: "x".repeat(2001),
      }),
    ).toThrow();
  });
});

describe("Decision", () => {
  it("accepts a valid decision", () => {
    const result = parseDecision(VALID_DECISION);
    expect(result.decision).toBe("escalate");
    expect(result.reasons).toEqual([
      "aggregate confidence 55.0 below escalate threshold 60.0",
    ]);
    expect(result.confidence).toBe(55.0);
    expect(result.risk_summary).toBe("new counterparty");
    expect(result.policy_version).toBe(3);
    expect(result.transaction_id).toBe("01xyz");
  });

  it("defaults reasons to empty array", () => {
    const result = parseDecision({
      decision: "approve",
      confidence: 95.0,
    });
    expect(result.reasons).toEqual([]);
  });

  it("defaults optional fields to null", () => {
    const result = parseDecision({
      decision: "reject",
      confidence: 10.0,
    });
    expect(result.risk_summary).toBeNull();
    expect(result.policy_version).toBeNull();
    expect(result.transaction_id).toBeNull();
  });

  it("rejects confidence outside 0-100", () => {
    expect(() =>
      parseDecision({ decision: "approve", confidence: -1 }),
    ).toThrow();
    expect(() =>
      parseDecision({ decision: "approve", confidence: 101 }),
    ).toThrow();
  });

  it("rejects invalid decision type", () => {
    expect(() =>
      parseDecision({ decision: "maybe", confidence: 50 }),
    ).toThrow();
  });
});
