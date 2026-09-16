import { z } from "zod";

export const ChainIdSchema = z.enum(["ethereum", "base", "arbitrum"]);
export type ChainId = z.infer<typeof ChainIdSchema>;

export const DecisionTypeSchema = z.enum(["approve", "reject", "escalate"]);
export type DecisionType = z.infer<typeof DecisionTypeSchema>;

const ADDRESS_RE = /^0x[0-9a-f]{40}$/i;

function validateAddress(v: string): string {
  if (!ADDRESS_RE.test(v)) {
    throw new Error("must be a 0x-prefixed 40-hex-char address");
  }
  return v.toLowerCase();
}

export const ScreenRequestSchema = z
  .object({
    agent_id: z.string().min(1),
    chain_id: ChainIdSchema,
    from_address: z.string().transform(validateAddress),
    to_address: z.string().transform(validateAddress).nullable().default(null),
    value_wei: z.number().int().nonnegative(),
    calldata: z.string().nullable().default(null),
    gas_limit: z.number().int().nonnegative().nullable().default(null),
    gas_price_wei: z.number().int().nonnegative().nullable().default(null),
    token: z
      .string()
      .transform(validateAddress)
      .nullable()
      .default(null),
    task_context: z.string().max(2000).nullable().default(null),
  })
  .strict();

export type ScreenRequest = z.infer<typeof ScreenRequestSchema>;

export const DecisionSchema = z.object({
  decision: DecisionTypeSchema,
  reasons: z.array(z.string()).default([]),
  confidence: z.number().min(0).max(100),
  risk_summary: z.string().nullable().default(null),
  policy_version: z.number().int().nullable().default(null),
  transaction_id: z.string().nullable().default(null),
});

export type Decision = z.infer<typeof DecisionSchema>;

export function parseScreenRequest(data: unknown): ScreenRequest {
  return ScreenRequestSchema.parse(data);
}

export function parseDecision(data: unknown): Decision {
  return DecisionSchema.parse(data);
}
