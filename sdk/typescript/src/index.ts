export { ChainIdSchema, DecisionTypeSchema, ScreenRequestSchema, DecisionSchema } from "./schemas.js";
export type { ChainId, DecisionType, ScreenRequest, Decision } from "./schemas.js";
export { parseScreenRequest, parseDecision } from "./schemas.js";

export {
  AgentThresholdError,
  TransportError,
  UnauthorizedError,
  ScreeningError,
  ScreeningRejectedError,
  ScreeningEscalatedError,
  ScreeningUnavailableError,
} from "./errors.js";

export {
  AgentThresholdClient,
  unsignedTxToScreenRequest,
} from "./client.js";
export type { Signer } from "./client.js";

export const VERSION = "0.1.0" as const;
