import type { Decision } from "./schemas.js";

export class AgentThresholdError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AgentThresholdError";
  }
}

export class TransportError extends AgentThresholdError {
  constructor(message: string) {
    super(message);
    this.name = "TransportError";
  }
}

export class UnauthorizedError extends AgentThresholdError {
  constructor(message: string) {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export class ScreeningError extends AgentThresholdError {
  decision?: Decision;

  constructor(message: string, decision?: Decision) {
    super(message);
    this.name = "ScreeningError";
    this.decision = decision;
  }
}

export class ScreeningRejectedError extends ScreeningError {
  constructor(decision: Decision) {
    super(describeDecision(decision), decision);
    this.name = "ScreeningRejectedError";
  }
}

export class ScreeningEscalatedError extends ScreeningError {
  constructor(decision: Decision) {
    super(describeDecision(decision), decision);
    this.name = "ScreeningEscalatedError";
  }
}

export class ScreeningUnavailableError extends ScreeningError {
  constructor(message: string) {
    super(message);
    this.name = "ScreeningUnavailableError";
  }
}

function describeDecision(decision: Decision): string {
  const reasons =
    decision.reasons.length > 0 ? decision.reasons.join("; ") : "no reasons";
  return (
    `transaction ${decision.decision} by AgentThreshold ` +
    `(confidence=${decision.confidence.toFixed(1)}, transaction_id=${decision.transaction_id}): ${reasons}`
  );
}
