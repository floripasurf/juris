"""Tenant authentication — the multi-tenant foundation (Phase 2, Track 5).

Mirrors the proven pattern: each firm gets an API key (``X-API-Key``); the request
resolves to a :class:`Tenant` used downstream to scope storage. With no tenants
configured the deployment stays **open** (everyone is the shared ``public``
tenant), so the co-located Phase-1 pilot keeps working unchanged.

Per-account storage isolation and the Remote local-agent (ADR-0015 Phase 2) build
on top of the Tenant resolved here.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException

PUBLIC_TENANT_ID = "public"


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
            key: Tenant(tenant_id) for tenant_id, key in tenants.items()
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
        if api_key is None:
            return None
        return self._by_key.get(api_key)


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
    return base / "tenants" / tenant.tenant_id
