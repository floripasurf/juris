"""Tenant authentication — the multi-tenant foundation (Phase 2, Track 5).

Mirrors the proven pattern: each firm gets an API key (``X-API-Key``); the request
resolves to a :class:`Tenant` used downstream to scope storage. With no tenants
configured the deployment stays **open** (everyone is the shared ``public``
tenant), so the co-located Phase-1 pilot keeps working unchanged.

Per-account storage isolation and the Remote local-agent (ADR-0015 Phase 2) build
on top of the Tenant resolved here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException

PUBLIC_TENANT_ID = "public"

# A tenant_id becomes a storage path segment — keep it to safe chars so a crafted
# id (with `/` or `..`) can't escape its directory.
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_tenant_id(tenant_id: str) -> str:
    if not _TENANT_ID_RE.match(tenant_id):
        msg = f"tenant_id inválido (use ^[a-zA-Z0-9_-]+$): {tenant_id!r}"
        raise ValueError(msg)
    return tenant_id


_HASH_PREFIX = "sha256:"
_HASHED_API_KEY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def hash_api_key(api_key: str) -> str:
    """``sha256:<hex>`` of an API key — store these in production, never the raw key.

    The explicit prefix removes any ambiguity between a stored hash and a stored
    plaintext key.
    """
    return _HASH_PREFIX + hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _validate_configured_tenant_id(tenant_id: object) -> str:
    if not isinstance(tenant_id, str):
        msg = f"tenant_id inválido (string obrigatória): {tenant_id!r}"
        raise ValueError(msg)
    validated = _validate_tenant_id(tenant_id)
    if validated == PUBLIC_TENANT_ID:
        msg = "tenant_id 'public' é reservado para modo aberto; configure um tenant próprio."
        raise ValueError(msg)
    return validated


def _validate_api_key_config(tenant_id: str, api_key: object) -> str:
    if not isinstance(api_key, str) or not api_key.strip():
        msg = f"API key inválida para tenant {tenant_id!r}: valor vazio ou não textual."
        raise ValueError(msg)
    if api_key != api_key.strip():
        msg = f"API key inválida para tenant {tenant_id!r}: remova espaços nas extremidades."
        raise ValueError(msg)
    if api_key.startswith(_HASH_PREFIX) and _HASHED_API_KEY_RE.fullmatch(api_key) is None:
        msg = f"API key inválida para tenant {tenant_id!r}: hash sha256 malformado."
        raise ValueError(msg)
    return api_key


@dataclass(frozen=True, slots=True)
class Tenant:
    """The firm a request belongs to."""

    tenant_id: str
    name: str = ""


class TenantRegistry:
    """Maps API keys to tenants. Empty ⇒ open deployment."""

    def __init__(self, tenants: Mapping[str, str]) -> None:
        # config is {tenant_id: api_key}; index by key for O(1) auth.
        by_key: dict[str, Tenant] = {}
        for tenant_id, raw_key in tenants.items():
            validated_tenant_id = _validate_configured_tenant_id(tenant_id)
            key = _validate_api_key_config(validated_tenant_id, raw_key)
            if key in by_key:
                msg = "API key duplicada em JURIS_TENANTS_FILE; cada tenant precisa de chave própria."
                raise ValueError(msg)
            by_key[key] = Tenant(validated_tenant_id)
        self._by_key = by_key

    @classmethod
    def from_file(cls, path: Path) -> TenantRegistry:
        """Load ``{tenant_id: api_key}`` from JSON; missing file ⇒ open."""
        if not path.exists():
            return cls({})
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            msg = "JURIS_TENANTS_FILE deve conter um objeto JSON {tenant_id: api_key}."
            raise ValueError(msg)
        return cls(data)

    @property
    def is_open(self) -> bool:
        return not self._by_key

    @property
    def tenant_ids(self) -> tuple[str, ...]:
        """Configured tenant ids, for production preflight checks."""
        return tuple(sorted({tenant.tenant_id for tenant in self._by_key.values()}))

    def authenticate(self, api_key: str | None) -> Tenant | None:
        """Match a key against stored values — plaintext (dev) or ``sha256:`` (prod).

        Constant-time comparison; the ``sha256:`` prefix decides unambiguously
        whether a stored value is a hash or a plaintext key.
        """
        if api_key is None:
            return None
        incoming_hash = hash_api_key(api_key)
        for stored, tenant in self._by_key.items():
            target = incoming_hash if stored.startswith(_HASH_PREFIX) else api_key
            if hmac.compare_digest(stored, target):
                return tenant
        return None


def resolve_tenant(
    registry: TenantRegistry, *, api_key: str | None, require_configured: bool = False
) -> Tenant:
    """Resolve the tenant for a request, or raise if the key is invalid.

    Args:
        require_configured: fail closed when no tenants are configured (instead of
            falling back to the open ``public`` tenant) — set in production.

    Raises:
        PermissionError: when tenants are required but absent, or the key is bad.
    """
    if registry.is_open:
        if require_configured:
            msg = "tenants exigidos mas nenhum configurado (JURIS_REQUIRE_TENANTS)."
            raise PermissionError(msg)
        return Tenant(PUBLIC_TENANT_ID)
    tenant = registry.authenticate(api_key)
    if tenant is None:
        msg = "API key ausente ou inválida."
        raise PermissionError(msg)
    return tenant


@lru_cache(maxsize=1)
def default_registry() -> TenantRegistry:
    """The process-wide registry, loaded from ``$JURIS_TENANTS_FILE`` (open if absent)."""
    return TenantRegistry.from_file(Path(os.environ.get("JURIS_TENANTS_FILE", "config/tenants.json")))


def _require_tenants() -> bool:
    """Whether to fail closed when no tenants are configured (``$JURIS_REQUIRE_TENANTS``)."""
    return os.environ.get("JURIS_REQUIRE_TENANTS", "").strip().lower() in {"1", "true", "yes"}


async def current_tenant(x_api_key: str | None = Header(default=None)) -> Tenant:
    """FastAPI dependency: resolve the request's tenant (401 if the key is bad).

    Binds ``tenant_id`` to the log context so every log in this request is
    attributable to its firm (per-tenant observability).
    """
    try:
        tenant = resolve_tenant(
            default_registry(), api_key=x_api_key, require_configured=_require_tenants()
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "tenant_invalid", "message": str(exc)},
        ) from exc
    from juris.core.observability import bind_tenant_log_context

    bind_tenant_log_context(tenant.tenant_id)
    return tenant


def tenant_scoped_dir(tenant: Tenant, base: Path) -> Path:
    """Per-account storage root: shared ``base`` for public, ``base/tenants/<id>`` otherwise."""
    if tenant.tenant_id == PUBLIC_TENANT_ID:
        return base
    return base / "tenants" / _validate_tenant_id(tenant.tenant_id)


def tenant_db_path(tenant: Tenant, *, base: Path | None = None) -> Path:
    """The tenant's LocalDB path — shared ``~/.juris/juris.db`` for public, isolated otherwise."""
    base = base or Path.home() / ".juris"
    return tenant_scoped_dir(tenant, base) / "juris.db"
