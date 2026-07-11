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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException

from juris.core.paths import juris_home

PUBLIC_TENANT_ID = "public"

# A tenant_id becomes a storage path segment — keep it to safe chars so a crafted
# id (with `/` or `..`) can't escape its directory.
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_tenant_id(tenant_id: str) -> str:
    """Validate a tenant id before it is used for routing, storage, or relay state."""
    if not _TENANT_ID_RE.match(tenant_id):
        msg = f"tenant_id inválido (use ^[a-zA-Z0-9_-]+$): {tenant_id!r}"
        raise ValueError(msg)
    return tenant_id


def _validate_tenant_id(tenant_id: str) -> str:
    return validate_tenant_id(tenant_id)


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


def _parse_expires_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        msg = f"expires_at inválido: {value!r}"
        raise ValueError(msg)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        msg = f"expires_at inválido: {value!r}"
        raise ValueError(msg) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_expired_at(expires_at: datetime | None, *, now: datetime) -> bool:
    return expires_at is not None and expires_at <= now


def _is_expired(value: object, *, now: datetime) -> bool:
    return _is_expired_at(_parse_expires_at(value), now=now)


def _earliest_expiration(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _key_from_structured_entry(
    tenant_id: str,
    key_id: str,
    entry: object,
    *,
    tenant_expires_at: datetime | None,
    now: datetime,
) -> tuple[str, datetime | None] | None:
    if isinstance(entry, str):
        return _validate_api_key_config(tenant_id, entry), tenant_expires_at
    if not isinstance(entry, Mapping):
        msg = f"API key inválida para tenant {tenant_id!r}/{key_id!r}: entrada deve ser string ou objeto."
        raise ValueError(msg)
    key_expires_at = _parse_expires_at(entry.get("expires_at"))
    if _is_expired_at(key_expires_at, now=now):
        return None
    key = entry.get("hash") or entry.get("api_key")
    if key is None:
        msg = f"API key inválida para tenant {tenant_id!r}/{key_id!r}: informe hash ou api_key."
        raise ValueError(msg)
    return _validate_api_key_config(tenant_id, key), _earliest_expiration(tenant_expires_at, key_expires_at)


def _active_api_key_bindings_for_tenant(
    tenant_id: str, raw_config: object, *, now: datetime
) -> tuple[tuple[str, datetime | None], ...]:
    """Return active stored key strings for one tenant.

    Backwards compatible formats:
    - ``"tenant": "sha256:..."`` or plaintext (dev legacy)
    - ``"tenant": {"trial_expires_at": "...", "keys": {"owner": {"hash": "sha256:..."}}}``
    Expired tenant/key entries are ignored, making a 30-day trial fail auth without
    deleting its local data immediately.
    """
    if isinstance(raw_config, str):
        return ((_validate_api_key_config(tenant_id, raw_config), None),)
    if not isinstance(raw_config, Mapping):
        msg = f"configuração inválida para tenant {tenant_id!r}: use string ou objeto."
        raise ValueError(msg)
    tenant_expires_at = _parse_expires_at(raw_config.get("trial_expires_at") or raw_config.get("expires_at"))
    if _is_expired_at(tenant_expires_at, now=now):
        return ()
    keys = raw_config.get("keys")
    if not isinstance(keys, Mapping) or not keys:
        msg = f"configuração inválida para tenant {tenant_id!r}: objeto precisa de keys não vazio."
        raise ValueError(msg)
    active: list[tuple[str, datetime | None]] = []
    for key_id, entry in keys.items():
        if not isinstance(key_id, str) or not key_id:
            msg = f"key_id inválido para tenant {tenant_id!r}: {key_id!r}"
            raise ValueError(msg)
        binding = _key_from_structured_entry(
            tenant_id, key_id, entry, tenant_expires_at=tenant_expires_at, now=now
        )
        if binding is not None:
            active.append(binding)
    return tuple(active)


@dataclass(frozen=True, slots=True)
class Tenant:
    """The firm a request belongs to."""

    tenant_id: str
    name: str = ""


@dataclass(frozen=True, slots=True)
class _KeyBinding:
    tenant: Tenant
    expires_at: datetime | None = None


class TenantRegistry:
    """Maps API keys to tenants. Empty ⇒ open deployment."""

    def __init__(self, tenants: Mapping[str, object], *, now_func: Callable[[], datetime] | None = None) -> None:
        # config is {tenant_id: api_key_or_structured_entry}; index by key for O(1) auth.
        self._now = now_func or (lambda: datetime.now(UTC))
        by_key: dict[str, _KeyBinding] = {}
        tenant_ids: set[str] = set()
        now = self._now()
        for tenant_id, raw_key in tenants.items():
            validated_tenant_id = _validate_configured_tenant_id(tenant_id)
            key_bindings = _active_api_key_bindings_for_tenant(validated_tenant_id, raw_key, now=now)
            if key_bindings:
                tenant_ids.add(validated_tenant_id)
            tenant = Tenant(validated_tenant_id)
            for key, expires_at in key_bindings:
                if key in by_key:
                    msg = "API key duplicada em JURIS_TENANTS_FILE; cada tenant precisa de chave própria."
                    raise ValueError(msg)
                by_key[key] = _KeyBinding(tenant=tenant, expires_at=expires_at)
        self._by_key = by_key
        self._tenant_ids = tenant_ids

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
        return tuple(sorted(self._tenant_ids))

    def authenticate(self, api_key: str | None) -> Tenant | None:
        """Match a key against stored values — plaintext (dev) or ``sha256:`` (prod).

        Constant-time comparison; the ``sha256:`` prefix decides unambiguously
        whether a stored value is a hash or a plaintext key.
        """
        if api_key is None:
            return None
        incoming_hash = hash_api_key(api_key)
        now = self._now()
        for stored, binding in self._by_key.items():
            target = incoming_hash if stored.startswith(_HASH_PREFIX) else api_key
            if hmac.compare_digest(stored, target) and not _is_expired_at(binding.expires_at, now=now):
                return binding.tenant
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


def _is_prod_environment(env: Mapping[str, str] | None = None) -> bool:
    env = env or os.environ
    return env.get("ENVIRONMENT", "").strip().lower() == "prod"


def require_tenants_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Whether tenant auth must fail closed.

    In development, ``JURIS_REQUIRE_TENANTS=1`` opts in explicitly. In production,
    ``ENVIRONMENT=prod`` is enough: forgetting the flag must not reopen the shared
    ``public`` tenant.
    """
    env = env or os.environ
    explicit = env.get("JURIS_REQUIRE_TENANTS", "").strip().lower() in {"1", "true", "yes"}
    return explicit or _is_prod_environment(env)


async def current_tenant(x_api_key: str | None = Header(default=None)) -> Tenant:
    """FastAPI dependency: resolve the request's tenant (401 if the key is bad).

    Binds ``tenant_id`` to the log context so every log in this request is
    attributable to its firm (per-tenant observability).
    """
    try:
        tenant = resolve_tenant(
            default_registry(), api_key=x_api_key, require_configured=require_tenants_enabled()
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "tenant_invalid", "message": str(exc)},
        ) from exc
    from juris.core.observability import bind_tenant_log_context

    bind_tenant_log_context(tenant.tenant_id)
    return tenant


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate cross-tenant admin routes with ``$JURIS_ADMIN_TOKEN`` (constant-time).

    Fail-closed: with no admin token configured the route is *disabled* (404, so its
    existence isn't advertised); with one configured, a missing/wrong header is 401.
    """
    import os
    import secrets

    expected = os.environ.get("JURIS_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=404, detail="not found")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail={"code": "admin_unauthorized", "message": "token admin inválido"})


def tenant_scoped_dir(tenant: Tenant, base: Path) -> Path:
    """Per-account storage root: shared ``base`` for public, ``base/tenants/<id>`` otherwise."""
    if tenant.tenant_id == PUBLIC_TENANT_ID:
        return base
    return base / "tenants" / _validate_tenant_id(tenant.tenant_id)


def tenant_db_path(tenant: Tenant, *, base: Path | None = None) -> Path:
    """The tenant's LocalDB path — shared ``~/.juris/juris.db`` for public, isolated otherwise."""
    base = base or juris_home()
    return tenant_scoped_dir(tenant, base) / "juris.db"
