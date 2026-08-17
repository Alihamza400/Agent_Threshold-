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