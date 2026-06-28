"""Application configuration via pydantic-settings."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
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
