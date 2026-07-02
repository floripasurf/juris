"""Application configuration via pydantic-settings."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    PROD = "prod"


class Settings(BaseSettings):
    """Central configuration — loaded from .env in dev, env vars in prod."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment ---
    environment: Environment = Environment.DEV
    log_level: str = "DEBUG"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://juris:juris_dev@localhost:5432/juris"
    database_url_sync: str = "postgresql+psycopg://juris:juris_dev@localhost:5432/juris"

    # --- Qdrant ---
    qdrant_url: str = "http://localhost:6333"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Web/API runtime ---
    api_rate_limit_per_minute: int = Field(
        120, validation_alias="JURIS_API_RATE_LIMIT_PER_MINUTE", ge=0
    )
    api_expensive_rate_limit_per_minute: int = Field(
        12, validation_alias="JURIS_API_EXPENSIVE_RATE_LIMIT_PER_MINUTE", ge=0
    )
    ws_agent_relay_rate_limit_per_minute: int = Field(
        30, validation_alias="JURIS_WS_AGENT_RELAY_RATE_LIMIT_PER_MINUTE", ge=0
    )
    rate_limit_redis_url: str = Field("", validation_alias="JURIS_RATE_LIMIT_REDIS_URL")
    connect_timeout_seconds: int = Field(900, validation_alias="JURIS_CONNECT_TIMEOUT_SECONDS", gt=0)
    tst_inteiro_teor_enabled: bool = Field(False, validation_alias="JURIS_TST_INTEIRO_TEOR_ENABLED")

    # --- Object Storage ---
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: str = "./storage"
    s3_endpoint_url: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_bucket: str = "juris"

    # --- Embeddings ---
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"

    # --- LLM Cloud ---
    anthropic_api_key: SecretStr | None = None

    # --- LLM Local ---
    ollama_url: str = "http://localhost:11434"

    # --- Alerts ---
    alert_smtp_host: str = ""
    alert_smtp_port: int = 587
    alert_smtp_user: str = ""
    alert_smtp_password: SecretStr | None = None
    alert_from_address: str = ""
    alert_to_addresses: str = ""  # comma-separated

    # --- ICP-Brasil Certificate ---
    cert_path: str | None = None
    cert_password: SecretStr | None = None
    advogado_cpf: str | None = None
    # PKCS#11 module for A3 hardware tokens (mTLS tribunals like TJMG)
    pkcs11_module: str = "/usr/local/lib/libeTPkcs11.dylib"
    token_pin: SecretStr | None = None  # optional; prompted if absent
    # Optional trust bundle for OpenSSL s_client in the PKCS#11 mTLS MNI path.
    # When unset, OpenSSL's default CA paths are used and still verified.
    mni_server_ca_pem_path: str = ""

    @property
    def is_dev(self) -> bool:
        return self.environment == Environment.DEV


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton settings instance."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings
