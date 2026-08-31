from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "staging", "production"] = Field(
        default="development", alias="ENV"
    )

    service_name: str = Field(default="ai_analyst_service", alias="SERVICE_NAME")
    port: int = Field(default=8012, alias="PORT")

    database_url: str = Field(..., alias="DATABASE_URL")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # Auth
    auth_jwt_public_key_path: str = Field(default="", alias="AUTH_JWT_PUBLIC_KEY_PATH")
    auth_jwt_algorithm: str = Field(default="RS256", alias="AUTH_JWT_ALGORITHM")
    auth_jwt_issuer: str = Field(default="auth_service", alias="AUTH_JWT_ISSUER")

    # Upstream services (read-only aggregation)
    market_data_service_url: str = Field(
        default="http://market_data_service:8002", alias="MARKET_DATA_SERVICE_URL"
    )
    risk_engine_service_url: str = Field(
        default="http://risk_engine_service:8007", alias="RISK_ENGINE_SERVICE_URL"
    )
    execution_engine_service_url: str = Field(
        default="http://execution_engine_service:8008", alias="EXECUTION_ENGINE_SERVICE_URL"
    )
    portfolio_management_service_url: str = Field(
        default="http://portfolio_management_service:8009",
        alias="PORTFOLIO_MANAGEMENT_SERVICE_URL",
    )

    # OTel
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    # DB pool
    db_pool_min_size: int = Field(default=5, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=20, alias="DB_POOL_MAX_SIZE")

    http_client_timeout_seconds: float = Field(
        default=15.0, alias="HTTP_CLIENT_TIMEOUT_SECONDS"
    )

    # ── LLM provider ─────────────────────────────────────────────────────────
    llm_provider: Literal["anthropic"] = Field(default="anthropic", alias="LLM_PROVIDER")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL"
    )
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")
    anthropic_api_version: str = Field(default="2023-06-01", alias="ANTHROPIC_API_VERSION")
    llm_max_tokens: int = Field(default=1024, alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.3, alias="LLM_TEMPERATURE")
    llm_request_timeout_seconds: float = Field(default=30.0, alias="LLM_REQUEST_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")

    # ── Caching ──────────────────────────────────────────────────────────────
    cache_ttl_seconds_default: int = Field(default=300, alias="CACHE_TTL_SECONDS_DEFAULT")
    cache_ttl_seconds_market_summary: int = Field(
        default=120, alias="CACHE_TTL_SECONDS_MARKET_SUMMARY"
    )
    cache_ttl_seconds_portfolio_review: int = Field(
        default=180, alias="CACHE_TTL_SECONDS_PORTFOLIO_REVIEW"
    )
    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")

    # ── Rate limiting ────────────────────────────────────────────────────────
    rate_limit_per_user_per_minute: int = Field(
        default=10, alias="RATE_LIMIT_PER_USER_PER_MINUTE"
    )
    rate_limit_global_per_minute: int = Field(
        default=120, alias="RATE_LIMIT_GLOBAL_PER_MINUTE"
    )
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")

    # ── Security ─────────────────────────────────────────────────────────────
    max_context_chars: int = Field(
        default=12_000, alias="MAX_CONTEXT_CHARS", description="Hard cap on serialized data context sent to the LLM"
    )
    max_user_note_chars: int = Field(default=500, alias="MAX_USER_NOTE_CHARS")


settings = Settings()  # type: ignore[call-arg]
