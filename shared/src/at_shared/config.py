"""Application configuration for shared infrastructure.

All settings are read from environment variables (see `.env.example`).
Secrets are never hardcoded; production secrets come from Vault/KMS.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Base settings shared across AgentThreshold services."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    # Database
    postgres_user: str = "agentthreshold"
    postgres_password: str = "agentthreshold_dev"
    postgres_db: str = "agentthreshold"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    # Redis
    redis_url: str = "redis://localhost:6380/0"

    # Auth
    jwt_secret: str = "change_me_generate_a_long_random_secret"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_hours: int = 24

    # OIDC / SSO (enterprise)
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    # Bootstrap admin
    bootstrap_admin_email: str = "admin@agentthreshold.dev"
    bootstrap_admin_password: str = "ChangeMe_Str0ng!"

    # CORS (dashboard SPA). Comma-separated explicit origins; empty means
    # permissive in development and locked-down (none) in production.
    cors_origins: str = ""

    # OWASP request-size cap for all HTTP services (Phase 9.1). Bodies larger
    # than this are rejected with 413 before any parsing (DoS hardening).
    max_request_body_bytes: int = 65536

    # Unresolved escalations expire after this many minutes and default to
    # reject (fail-closed human review queue).
    escalation_ttl_minutes: int = 60

    # Escalation notification service (Phase 8.4).
    # Per-org delivery endpoint mapping, format: "org_id=url" pairs separated
    # by commas (e.g. "org1=https://hooks.slack.com/... ,org2=https://.../hook").
    # The endpoint receives a POST with the escalation payload JSON. Empty
    # means delivery is disabled (queue-only) — the human queue still works.
    notification_webhooks: str = ""
    # Slack-style hook semantics: when true, the payload is wrapped in the
    # Slack incoming-webhook envelope ({ "text": ... }).
    notification_slack_format: bool = True
    # Delivery retry policy (target: 99% delivered within 5s of creation).
    notify_poll_seconds: float = 0.5
    notify_max_attempts: int = 8
    notify_backoff_base_seconds: float = 1.0

    # Execution adapter (task 8.5).
    # Internal service-to-service API key for the execution endpoints (from
    # the secrets manager in production; the gateway passes it through).
    execution_api_key: str = "change_me_execution_key"
    # Poll cadence for the confirm/reorg/stuck worker.
    execution_poll_seconds: float = 1.0
    # A broadcast tx with no receipt after this many seconds is flagged stuck
    # and triggers the RBF/cancel re-screen flow (TRD 5.10).
    execution_stuck_after_seconds: float = 60.0
    # Single-use decision token lifetime (seconds). The signed tx must be
    # submitted within this window or a new token must be issued (re-approval
    # is NOT automatic — fail-closed).
    decision_token_ttl_seconds: int = 300
    # RBF/cancel replacement: gas price bump above the original (percent).
    execution_rbf_gas_bump_pct: float = 20.0
    execution_cancel_gas_bump_pct: float = 20.0
    # Max broadcast attempts (exponential backoff) before surfacing an alert.
    execution_max_broadcast_attempts: int = 5
    execution_backoff_base_seconds: float = 2.0

    # An APPROVE from the deterministic policy engine is downgraded to
    # ESCALATE when the aggregate advisory confidence (0-100) falls below this
    # threshold (Phase 8 orchestrator, 8.3).
    escalate_below_confidence: float = 60.0

    # Simulation enforcement in the screening pipeline (Phase 8 orchestrator).
    #   "required" (default, production): a missing/failed simulation backend
    #     fails closed -> escalate, never approve (SR-04, zero silent bypass).
    #   "disabled": skips simulation entirely. DEV/TEST ONLY — production must
    #     never run with simulation disabled.
    simulation_mode: str = "required"

    # Blockchain (Phase 5)
    # Primary + fallback RPC endpoints per chain, comma-separated if more.
    eth_rpc_url: str = ""
    eth_rpc_fallback_url: str = ""
    base_rpc_url: str = ""
    base_rpc_fallback_url: str = ""
    # Gas safety buffer (fraction above eth_estimateGas) — default 20%.
    gas_buffer_pct: float = 20.0
    # Default confirmation depth: 2 for L2, 12 for mainnet.
    eth_confirmations: int = 12
    base_confirmations: int = 2
    # Anvil (fork-per-request simulation). Empty => use process spawn on PATH.
    anvil_rpc_url: str = ""
    # Chainlink aggregator addresses (ETH/USD). Empty => fallback oracle.
    eth_usd_aggregator: str = ""
    # RPC timeout (seconds) — fail-closed on slow providers.
    rpc_timeout_seconds: float = 5.0

    # On-chain audit anchoring (Phase 6.6, FR-AUDIT-01).
    # RPC endpoint the anchor worker submits through; the audit contract lives
    # on the chain this endpoint serves. EIP-155 chain id for transaction
    # signing (anvil defaults to 31337).
    anchor_rpc_url: str = ""
    anchor_chain_id: int = 31337
    # AuditAnchor (proxy) address the service submits Merkle roots to.
    anchor_contract_address: str = ""
    # EOA that is an `isAuthorizedAnchor` on the contract. Loaded from a
    # secret store (Vault/KMS) in production, never committed.
    anchor_wallet_private_key: str = ""
    # Batching cadence (6.6): flush every `anchor_batch_max_records` records
    # or `anchor_batch_interval_seconds` whichever comes first.
    anchor_batch_max_records: int = 1000
    anchor_batch_interval_seconds: float = 900.0
    # Confirmation depth and submission retry/backoff for the worker.
    anchor_confirmations: int = 1
    anchor_max_attempts: int = 5
    anchor_backoff_base_seconds: float = 5.0

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()