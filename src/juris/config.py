"""Application configuration via pydantic-settings."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

import structlog
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger(__name__)


# URLs que existem só como conveniência de dev. Em prod elas indicam env var
# esquecida; com JURIS_STRICT_PROD_URLS=1 o load falha fechado (deploy docker que
# realmente usa esses serviços). Sem strict, apenas avisa — o piloto SQLite-first
# não define essas URLs e não pode ser derrubado por isso.
_DEV_DEFAULT_URLS = {
    "database_url": "postgresql+asyncpg://juris:juris_dev@localhost:5432/juris",
    "database_url_sync": "postgresql+psycopg://juris:juris_dev@localhost:5432/juris",
    "qdrant_url": "http://localhost:6333",
    "redis_url": "redis://localhost:6379/0",
    "ollama_url": "http://localhost:11434",
}


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
    rate_limit_fail_closed: bool = Field(False, validation_alias="JURIS_RATE_LIMIT_FAIL_CLOSED")
    billing_pix_link: str = Field("", validation_alias="JURIS_BILLING_PIX_LINK")
    trusted_proxy: bool = Field(False, validation_alias="JURIS_TRUSTED_PROXY")
    connect_timeout_seconds: int = Field(900, validation_alias="JURIS_CONNECT_TIMEOUT_SECONDS", gt=0)
    tst_inteiro_teor_enabled: bool = Field(False, validation_alias="JURIS_TST_INTEIRO_TEOR_ENABLED")
    clock_skew_probe_enabled: bool = Field(
        False,
        validation_alias="JURIS_CLOCK_SKEW_PROBE",
        description="Se 1, o preflight de assinatura sonda o header Date do tribunal para medir clock skew (aviso).",
    )
    ai_browser_provider: Literal["claude", "chatgpt"] | None = Field(
        None,
        validation_alias="JURIS_AI_BROWSER_PROVIDER",
        description="Fornecedor da sessão de browser declarado pelo advogado (ADR-0018).",
    )
    strict_prod_urls: bool = Field(
        False,
        validation_alias="JURIS_STRICT_PROD_URLS",
        description="Em prod, falha fechado se alguma URL de backend ainda for o default localhost de dev.",
    )

    # --- Prazo ---
    parte_representada: str = Field(
        "",
        validation_alias="JURIS_PARTE_REPRESENTADA",
        description=(
            "Ente representado para prazo em dobro (arts. 180/183/186 CPC): "
            "'', 'fazenda', 'mp' ou 'defensoria'. Default '' = sem dobra, o "
            "comportamento correto para o deployment single-tenant atual. Em "
            "multi-tenant isso deve virar um registro por tenant/processo em vez "
            "de config global de deployment — follow-up explícito; "
            "compute_prazos() já aceita parte_representada por chamada."
        ),
    )

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

    # --- LLM: cadeia por CLI de assinatura (Task 2 canário) ---
    # Gated: draft_backend fica "ollama" e cli_llm_tenants fica vazia até uma decisão
    # humana registrada (risco de ToS) ligar isto em produção — ver .env.example.
    draft_backend: str = Field("ollama", validation_alias="JURIS_DRAFT_BACKEND")  # ollama | cli
    cli_llm_tenants: str = Field(
        "", validation_alias="JURIS_CLI_LLM_TENANTS"
    )  # allowlist CSV; vazia = ninguém
    cli_llm_model: str = Field("gpt-5.5", validation_alias="JURIS_CLI_LLM_MODEL")
    cli_llm_effort: str = Field("low", validation_alias="JURIS_CLI_LLM_EFFORT")
    cli_fallback_model: str = Field("haiku", validation_alias="JURIS_CLI_FALLBACK_MODEL")
    codex_bin: str = Field("codex", validation_alias="JURIS_CODEX_BIN")
    claude_bin: str = Field("claude", validation_alias="JURIS_CLAUDE_BIN")
    ollama_model: str = Field("qwen3:8b", validation_alias="JURIS_OLLAMA_MODEL")

    @property
    def cli_llm_tenant_allowlist(self) -> frozenset[str]:
        """Parsed CSV allowlist for the CLI-signature draft chain (Task 2 canário).

        Empty string (the default) parses to an empty set — nobody is allowlisted, so
        the chain stays inert regardless of ``draft_backend``.
        """
        return frozenset(t.strip() for t in self.cli_llm_tenants.split(",") if t.strip())

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

    def dev_default_leaks(self) -> list[str]:
        """Nomes de URLs ainda no default localhost de dev quando ENVIRONMENT=prod.

        Vazio fora de prod, ou quando todas as URLs foram sobrescritas.
        """
        if self.environment != Environment.PROD:
            return []
        return [
            name
            for name, dev_value in _DEV_DEFAULT_URLS.items()
            if getattr(self, name) == dev_value
        ]

    @model_validator(mode="after")
    def _warn_or_reject_dev_defaults_in_prod(self) -> Settings:
        """Avisa (ou, com strict, rejeita) URLs de backend ainda em default de dev sob prod."""
        leaked = self.dev_default_leaks()
        if not leaked:
            return self
        if self.strict_prod_urls:
            joined = ", ".join(sorted(leaked))
            msg = (
                f"ENVIRONMENT=prod exige override explícito para: {joined}. "
                "Defina as env vars correspondentes (ex.: DATABASE_URL=...) "
                "antes de subir, ou desative JURIS_STRICT_PROD_URLS."
            )
            raise ValueError(msg)
        log.warning("prod_dev_default_urls", leaked=sorted(leaked))
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton settings instance."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings
