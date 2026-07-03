"""Anonymous trial/access-key issuance for the public Causia landing."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from juris.web.auth import hash_api_key, validate_tenant_id


@dataclass(frozen=True, slots=True)
class TrialCredentials:
    tenant_id: str
    api_key: str
    expires_at: str
    agent_token: str
    relay_url: str

    @property
    def agent_command(self) -> str:
        return (
            f"JURIS_AGENT_TOKEN={self.agent_token} "
            f"juris agent connect-relay {self.relay_url} --tenant {self.tenant_id}"
        )


@dataclass(frozen=True, slots=True)
class IssuedAccessKey:
    tenant_id: str
    key_id: str
    api_key: str
    expires_at: str | None


@dataclass(frozen=True, slots=True)
class AgentPairing:
    tenant_id: str
    agent_token: str
    relay_url: str

    @property
    def agent_command(self) -> str:
        return (
            f"JURIS_AGENT_TOKEN={self.agent_token} "
            f"juris agent connect-relay {self.relay_url} --tenant {self.tenant_id}"
        )


def tenants_file_path() -> Path:
    return Path(os.environ.get("JURIS_TENANTS_FILE", "config/tenants.json"))


def agents_file_path() -> Path | None:
    configured = os.environ.get("JURIS_AGENTS_FILE", "").strip()
    return Path(configured) if configured else None


def trial_days() -> int:
    raw = os.environ.get("JURIS_TRIAL_DAYS", "30").strip()
    try:
        days = int(raw)
    except ValueError:
        days = 30
    return max(1, min(days, 90))


def trial_relay_url() -> str:
    return os.environ.get("JURIS_TRIAL_RELAY_URL", "wss://causia.com.br/ws/agent-relay").strip()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json_object(path: Path) -> dict[str, object]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path} deve conter um objeto JSON."
        raise ValueError(msg)
    return data


@contextmanager
def _locked_json(path: Path) -> Iterator[MutableMapping[str, object]]:
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        raw = fh.read().strip()
        data: dict[str, object] = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            msg = f"{path} deve conter um objeto JSON."
            raise ValueError(msg)
        yield data
        fh.seek(0)
        fh.truncate()
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())


def _clear_auth_caches() -> None:
    from juris.api.agent_config import _load_agent_bindings
    from juris.web.auth import default_registry

    default_registry.cache_clear()
    cast(Any, _load_agent_bindings).cache_clear()


def create_trial_access(
    *,
    tenants_path: Path | None = None,
    agents_path: Path | None = None,
    now: datetime | None = None,
) -> TrialCredentials:
    """Create one anonymous 30-day tenant and return raw secrets once."""
    tenants_path = tenants_path or tenants_file_path()
    agents_path = agents_path if agents_path is not None else agents_file_path()
    now = now or _utc_now()
    expires_at = now + timedelta(days=trial_days())
    relay_url = trial_relay_url()

    for _ in range(10):
        tenant_id = f"trial_{secrets.token_hex(8)}"
        api_key = f"causia_{secrets.token_urlsafe(32)}"
        agent_token = secrets.token_urlsafe(32)
        with _locked_json(tenants_path) as tenants:
            if tenant_id in tenants:
                continue
            tenants[tenant_id] = {
                "kind": "trial",
                "created_at": _iso(now),
                "trial_expires_at": _iso(expires_at),
                "keys": {
                    "owner": {
                        "hash": hash_api_key(api_key),
                        "label": "titular",
                        "created_at": _iso(now),
                        "expires_at": _iso(expires_at),
                    }
                },
            }
            break
    else:
        msg = "não foi possível gerar tenant de teste único."
        raise RuntimeError(msg)

    if agents_path is not None:
        with _locked_json(agents_path) as agents:
            agents[tenant_id] = {"url": relay_url, "token": agent_token, "transport": "relay"}
    _clear_auth_caches()
    return TrialCredentials(
        tenant_id=tenant_id,
        api_key=api_key,
        expires_at=_iso(expires_at),
        agent_token=agent_token,
        relay_url=relay_url,
    )


def _structured_tenant_entry(raw: object, *, now: datetime) -> dict[str, object]:
    if isinstance(raw, str):
        return {
            "kind": "account",
            "created_at": _iso(now),
            "keys": {"owner": {"hash": raw, "label": "principal", "created_at": _iso(now)}},
        }
    if isinstance(raw, dict):
        raw.setdefault("keys", {})
        return raw
    msg = "entrada de tenant inválida."
    raise ValueError(msg)


def issue_access_key(
    tenant_id: str,
    *,
    label: str = "equipe",
    tenants_path: Path | None = None,
    now: datetime | None = None,
) -> IssuedAccessKey:
    """Issue an extra API key for the same tenant, e.g. intern or colleague access."""
    tenant_id = validate_tenant_id(tenant_id)
    tenants_path = tenants_path or tenants_file_path()
    now = now or _utc_now()
    raw_key = f"causia_{secrets.token_urlsafe(32)}"
    key_id = f"key_{secrets.token_hex(6)}"
    with _locked_json(tenants_path) as tenants:
        if tenant_id not in tenants:
            msg = f"tenant não encontrado: {tenant_id}"
            raise KeyError(msg)
        entry = _structured_tenant_entry(tenants[tenant_id], now=now)
        expires_at = entry.get("trial_expires_at") or entry.get("expires_at")
        keys = entry.setdefault("keys", {})
        if not isinstance(keys, dict):
            msg = "entrada de tenant inválida: keys deve ser objeto."
            raise ValueError(msg)
        keys[key_id] = {
            "hash": hash_api_key(raw_key),
            "label": label.strip()[:80] or "equipe",
            "created_at": _iso(now),
            "expires_at": expires_at,
        }
        tenants[tenant_id] = entry
    _clear_auth_caches()
    return IssuedAccessKey(
        tenant_id=tenant_id,
        key_id=key_id,
        api_key=raw_key,
        expires_at=expires_at if isinstance(expires_at, str) else None,
    )


def rotate_agent_pairing(
    tenant_id: str,
    *,
    agents_path: Path | None = None,
) -> AgentPairing:
    """Rotate the tenant's relay token and return the raw agent command once."""
    tenant_id = validate_tenant_id(tenant_id)
    agents_path = agents_path if agents_path is not None else agents_file_path()
    if agents_path is None:
        msg = "JURIS_AGENTS_FILE não configurado; não é possível gerar comando do agente."
        raise RuntimeError(msg)
    agent_token = secrets.token_urlsafe(32)
    relay_url = trial_relay_url()
    with _locked_json(agents_path) as agents:
        current = agents.get(tenant_id)
        if isinstance(current, Mapping):
            relay_url = str(current.get("url") or relay_url)
        agents[tenant_id] = {"url": relay_url, "token": agent_token, "transport": "relay"}
    _clear_auth_caches()
    return AgentPairing(tenant_id=tenant_id, agent_token=agent_token, relay_url=relay_url)


def read_tenant_access_summary(tenant_id: str, *, tenants_path: Path | None = None) -> dict[str, object]:
    tenant_id = validate_tenant_id(tenant_id)
    tenants_path = tenants_path or tenants_file_path()
    data = _load_json_object(tenants_path)
    raw = data.get(tenant_id)
    if isinstance(raw, str):
        return {
            "tenant_id": tenant_id,
            "trial": False,
            "expires_at": None,
            "keys": [{"id": "owner", "label": "principal"}],
        }
    if not isinstance(raw, dict):
        return {"tenant_id": tenant_id, "trial": False, "expires_at": None, "keys": []}
    raw_keys = raw.get("keys")
    keys: Mapping[str, object] = raw_keys if isinstance(raw_keys, dict) else {}
    return {
        "tenant_id": tenant_id,
        "trial": raw.get("kind") == "trial",
        "expires_at": raw.get("trial_expires_at") or raw.get("expires_at"),
        "keys": [
            {"id": key_id, "label": entry.get("label", key_id) if isinstance(entry, dict) else key_id}
            for key_id, entry in keys.items()
        ],
    }
