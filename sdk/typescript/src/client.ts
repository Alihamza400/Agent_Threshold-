import type { ChainId, Decision, ScreenRequest } from "./schemas.js";
import { parseDecision } from "./schemas.js";
import {
  ScreeningEscalatedError,
  ScreeningRejectedError,
  ScreeningUnavailableError,
  TransportError,
  UnauthorizedError,
} from "./errors.js";

export type Signer = (unsignedTx: Record<string, unknown>) => unknown;

interface UnsignedTx {
  from: string;
  to?: string;
  value: string | number;
  data?: string;
  gas?: string | number;
  gasPrice?: string | number;
}

interface ClientOptions {
  timeout?: number;
  maxRetries?: number;
}

const SDK_VERSION = "0.1.0";

export class AgentThresholdClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private closed = false;

  constructor(baseUrl: string, apiKey: string, options: ClientOptions = {}) {
    if (!baseUrl || !apiKey) {
      throw new Error("baseUrl and apiKey are required");
    }
    const { timeout = 10_000, maxRetries = 0 } = options;
    if (maxRetries < 0) {
      throw new Error("maxRetries must be >= 0");
    }
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.apiKey = apiKey;
    this.timeout = timeout;
    this.maxRetries = maxRetries;
  }

  async screen(request: ScreenRequest): Promise<Decision> {
    this.assertNotClosed();
    let lastError: unknown;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const response = await fetch(
          `${this.baseUrl}/v1/transactions/screen`,
          {
            method: "POST",
            headers: this.headers(),
            body: JSON.stringify(request),
            signal: AbortSignal.timeout(this.timeout),
          },
        );
        return await this.decode(response);
      } catch (error) {
        lastError = error;
        if (error instanceof UnauthorizedError) {
          throw error;
        }
        if (error instanceof ScreeningUnavailableError) {
          throw error;
        }
        if (error instanceof ScreeningRejectedError) {
          throw error;
        }
        if (error instanceof ScreeningEscalatedError) {
          throw error;
        }
        if (error instanceof TransportError) {
          if (attempt < this.maxRetries) {
            await sleep(200 * (attempt + 1));
            continue;
          }
          throw error;
        }
      }
    }
    throw new TransportError(
      `screening request failed after ${this.maxRetries} retries: ${String(lastError)}`,
    );
  }

  async screenAndSign(
    signer: Signer,
    params: {
      agentId: string;
      chainId: ChainId;
      fromAddress: string;
      toAddress?: string;
      valueWei: number;
      calldata?: string;
      gasLimit?: number;
      gasPriceWei?: number;
      token?: string;
      taskContext?: string;
    },
  ): Promise<unknown> {
    const request: ScreenRequest = {
      agent_id: params.agentId,
      chain_id: params.chainId,
      from_address: params.fromAddress,
      to_address: params.toAddress ?? null,
      value_wei: params.valueWei,
      calldata: params.calldata ?? null,
      gas_limit: params.gasLimit ?? null,
      gas_price_wei: params.gasPriceWei ?? null,
      token: params.token ?? null,
      task_context: params.taskContext ?? null,
    };
    const decision = await this.screen(request);
    return this.signIfApproved(signer, decision, request);
  }

  async screenAndSignTx(
    signer: Signer,
    unsignedTx: UnsignedTx,
    params: {
      agentId: string;
      chainId: ChainId;
      taskContext?: string;
    },
  ): Promise<unknown> {
    const request = unsignedTxToScreenRequest(unsignedTx, {
      agentId: params.agentId,
      chainId: params.chainId,
      taskContext: params.taskContext,
    });
    const decision = await this.screen(request);
    return this.signIfApproved(signer, decision, request);
  }

  close(): void {
    this.closed = true;
  }

  private assertNotClosed(): void {
    if (this.closed) {
      throw new Error("client is closed");
    }
  }

  private headers(): Record<string, string> {
    return {
      "X-API-Key": this.apiKey,
      "Content-Type": "application/json",
      "User-Agent": `agentthreshold-sdk/${SDK_VERSION}`,
    };
  }

  private async decode(response: Response): Promise<Decision> {
    if (response.status === 401) {
      throw new UnauthorizedError(
        "API key rejected (401); check the key value and agent scope",
      );
    }
    if (response.status === 429) {
      const text = await response.text();
      throw new ScreeningUnavailableError(`rate limited (429): ${text}`);
    }
    if (response.status >= 500) {
      throw new ScreeningUnavailableError(
        `screening unavailable (${response.status})`,
      );
    }
    if (response.status !== 200) {
      const text = await response.text();
      throw new TransportError(
        `unexpected status ${response.status} from screening API: ${text.slice(0, 200)}`,
      );
    }
    try {
      const body: unknown = await response.json();
      return parseDecision(body);
    } catch (error) {
      throw new ScreeningUnavailableError(
        `malformed decision body: ${String(error)}`,
      );
    }
  }

  private signIfApproved(
    signer: Signer,
    decision: Decision,
    request: ScreenRequest,
  ): unknown {
    if (decision.decision === "approve") {
      return signer(unsignedTxFromRequest(request));
    }
    if (decision.decision === "reject") {
      throw new ScreeningRejectedError(decision);
    }
    throw new ScreeningEscalatedError(decision);
  }
}

function unsignedTxFromRequest(
  request: ScreenRequest,
): Record<string, unknown> {
  const tx: Record<string, unknown> = {
    from: request.from_address,
    value: request.value_wei,
  };
  if (request.to_address) {
    tx.to = request.to_address;
  }
  if (request.calldata) {
    tx.data = request.calldata;
  }
  if (request.gas_limit != null) {
    tx.gas = request.gas_limit;
  }
  if (request.gas_price_wei != null) {
    tx.gasPrice = request.gas_price_wei;
  }
  return tx;
}

function toInt(value: unknown, name: string): number {
  if (typeof value === "boolean") {
    throw new InvalidUnsignedTxError(
      `'${name}' must be an integer or 0x-hex string, got bool`,
    );
  }
  if (typeof value === "number") {
    if (!Number.isInteger(value)) {
      throw new InvalidUnsignedTxError(
        `'${name}' must be an integer, got float`,
      );
    }
    return value;
  }
  if (
    typeof value === "string" &&
    value.toLowerCase().startsWith("0x")
  ) {
    const parsed = Number.parseInt(value, 16);
    if (Number.isNaN(parsed)) {
      throw new InvalidUnsignedTxError(
        `'${name}' is not a valid 0x-hex integer: ${value}`,
      );
    }
    return parsed;
  }
  throw new InvalidUnsignedTxError(
    `'${name}' must be an integer or 0x-hex string, got ${typeof value}`,
  );
}

class InvalidUnsignedTxError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidUnsignedTxError";
  }
}

export function unsignedTxToScreenRequest(
  unsignedTx: UnsignedTx,
  params: {
    agentId: string;
    chainId: ChainId;
    taskContext?: string;
  },
): ScreenRequest {
  if (!unsignedTx || typeof unsignedTx !== "object") {
    throw new InvalidUnsignedTxError("unsignedTx must be an object");
  }
  if (!("from" in unsignedTx)) {
    throw new InvalidUnsignedTxError(
      "unsigned tx is missing required field 'from'",
    );
  }
  if (!("value" in unsignedTx)) {
    throw new InvalidUnsignedTxError(
      "unsigned tx is missing required field 'value'",
    );
  }
  try {
    return {
      agent_id: params.agentId,
      chain_id: params.chainId,
      from_address: String(unsignedTx.from).toLowerCase(),
      to_address: unsignedTx.to
        ? String(unsignedTx.to).toLowerCase()
        : null,
      value_wei: toInt(unsignedTx.value, "value"),
      calldata: unsignedTx.data ? String(unsignedTx.data) : null,
      gas_limit:
        unsignedTx.gas != null ? toInt(unsignedTx.gas, "gas") : null,
      gas_price_wei:
        unsignedTx.gasPrice != null
          ? toInt(unsignedTx.gasPrice, "gasPrice")
          : null,
      token: null,
      task_context: params.taskContext ?? null,
    };
  } catch (error) {
    if (error instanceof InvalidUnsignedTxError) {
      throw error;
    }
    throw new InvalidUnsignedTxError(
      `could not build screen request from unsigned tx: ${String(error)}`,
    );
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
