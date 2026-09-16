"""Application configuration for shared infrastructure.

All settings are read from environment variables (see `.env.example`).
Secrets are never hardcoded; production secrets come from Vault/KMS.
"""

from __future__ import annotations

import sys
from functools import lru_cache

from pydantic import model_validator
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
    notification_webhooks: str = ""
    notification_slack_format: bool = True
    notify_poll_seconds: float = 0.5
    notify_max_attempts: int = 8
    notify_backoff_base_seconds: float = 1.0

    # Incident response / on-call paging (Phase 9.6).
    pagerduty_routing_key: str = ""
    incident_webhook_url: str = ""
    incident_api_token: str = "change_me_incident_api_token"
    incident_poll_seconds: float = 0.5
    incident_max_attempts: int = 8
    incident_backoff_base_seconds: float = 1.0

    # Execution adapter (task 8.5).
    execution_api_key: str = "change_me_execution_key"
    execution_poll_seconds: float = 1.0
    execution_stuck_after_seconds: float = 60.0
    decision_token_ttl_seconds: int = 300
    execution_rbf_gas_bump_pct: float = 20.0
    execution_cancel_gas_bump_pct: float = 20.0
    execution_max_broadcast_attempts: int = 5
    execution_backoff_base_seconds: float = 2.0

    escalate_below_confidence: float = 60.0
    simulation_mode: str = "required"

    # Blockchain (Phase 5)
    eth_rpc_url: str = ""
    eth_rpc_fallback_url: str = ""
    base_rpc_url: str = ""
    base_rpc_fallback_url: str = ""
    gas_buffer_pct: float = 20.0
    eth_confirmations: int = 12
    base_confirmations: int = 2
    anvil_rpc_url: str = ""
    eth_usd_aggregator: str = ""
    rpc_timeout_seconds: float = 5.0

    # On-chain audit anchoring (Phase 6.6, FR-AUDIT-01).
    anchor_rpc_url: str = ""
    anchor_chain_id: int = 31337
    anchor_contract_address: str = ""
    anchor_wallet_private_key: str = ""
    anchor_batch_max_records: int = 1000
    anchor_batch_interval_seconds: float = 900.0
    anchor_confirmations: int = 1
    anchor_max_attempts: int = 5
    anchor_backoff_base_seconds: float = 5.0

    @model_validator(mode="after")
    def _reject_default_secrets_in_production(self) -> Settings:
        """Fail-fast on startup if well-known placeholder secrets are used in production."""
        if not self.is_production:
            return self

        default_secrets: dict[str, str] = {
            "jwt_secret": "change_me_generate_a_long_random_secret",
            "bootstrap_admin_password": "ChangeMe_Str0ng!",
            "execution_api_key": "change_me_execution_key",
            "incident_api_token": "change_me_incident_api_token",
        }
        violations = [k for k, default in default_secrets.items() if getattr(self, k) == default]
        if violations:
            msg = (
                f"SECURITY: Refusing to start in production with default secrets: "
                f"{', '.join(violations)}. Set these via environment variables or Vault/KMS."
            )
            print(msg, file=sys.stderr)
            raise ValueError(msg)
        return self

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