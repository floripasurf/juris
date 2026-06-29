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


def hash_api_key(api_key: str) -> str:
    """SHA-256 of an API key — store these in production, never the raw key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Tenant:
    """The firm a request belongs to."""

    tenant_id: str
    name: str = ""


class TenantRegistry:
    """Maps API keys to tenants. Empty ⇒ open deployment."""

    def __init__(self, tenants: dict[str, str]) -> None:
        # config is {tenant_id: api_key}; index by key for O(1) auth.
        self._by_key: dict[str, Tenant] = {
            key: Tenant(_validate_tenant_id(tenant_id)) for tenant_id, key in tenants.items()
        }

    @classmethod
    def from_file(cls, path: Path) -> TenantRegistry:
        """Load ``{tenant_id: api_key}`` from JSON; missing file ⇒ open."""
        if not path.exists():
            return cls({})
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @property
    def is_open(self) -> bool:
        return not self._by_key

    def authenticate(self, api_key: str | None) -> Tenant | None:
        """Match a key against stored values — plaintext (dev) or sha256 (prod).

        Constant-time comparison; a stored value is treated as a hash when it's
        the incoming key's sha256, else as a plaintext key.
        """
        if api_key is None:
            return None
        incoming_hash = hash_api_key(api_key)
        for stored, tenant in self._by_key.items():
            if hmac.compare_digest(stored, api_key) or hmac.compare_digest(stored, incoming_hash):
                return tenant
        return None


def resolve_tenant(registry: TenantRegistry, *, api_key: str | None) -> Tenant:
    """Resolve the tenant for a request, or raise if the key is invalid.

    Raises:
        PermissionError: when tenants are configured and the key is missing/invalid.
    """
    if registry.is_open:
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


async def current_tenant(x_api_key: str | None = Header(default=None)) -> Tenant:
    """FastAPI dependency: resolve the request's tenant (401 if the key is bad)."""
    try:
        return resolve_tenant(default_registry(), api_key=x_api_key)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def tenant_scoped_dir(tenant: Tenant, base: Path) -> Path:
    """Per-account storage root: shared ``base`` for public, ``base/tenants/<id>`` otherwise."""
    if tenant.tenant_id == PUBLIC_TENANT_ID:
        return base
    return base / "tenants" / _validate_tenant_id(tenant.tenant_id)


def tenant_db_path(tenant: Tenant, *, base: Path | None = None) -> Path:
    """The tenant's LocalDB path — shared ``~/.juris/juris.db`` for public, isolated otherwise."""
    base = base or Path.home() / ".juris"
    return tenant_scoped_dir(tenant, base) / "juris.db"
