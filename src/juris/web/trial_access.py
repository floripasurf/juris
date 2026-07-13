"""Anonymous trial/access-key issuance for the public Causia landing."""

from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from juris.core.paths import restrict_file
from juris.web.auth import hash_api_key, validate_tenant_id


class TrialCapacityError(RuntimeError):
    """Raised when anonymous trial capacity is exhausted."""


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


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def trial_max_active() -> int:
    raw = os.environ.get("JURIS_TRIAL_MAX_ACTIVE", "500").strip()
    try:
        limit = int(raw)
    except ValueError:
        limit = 500
    return max(1, min(limit, 10_000))


def trial_max_new_per_day() -> int:
    raw = os.environ.get("JURIS_TRIAL_MAX_NEW_PER_DAY", "100").strip()
    try:
        limit = int(raw)
    except ValueError:
        limit = 100
    return max(0, min(limit, 10_000))


def trial_relay_url() -> str:
    return os.environ.get("JURIS_TRIAL_RELAY_URL", "wss://causia.com.br/ws/agent-relay").strip()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: object) -> datetime | None:
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


def _trial_expiration(raw: object) -> datetime | None:
    if not isinstance(raw, Mapping) or raw.get("kind") != "trial":
        return None
    return _parse_iso_datetime(raw.get("trial_expires_at") or raw.get("expires_at"))


def _is_expired_trial(raw: object, *, now: datetime) -> bool:
    expires_at = _trial_expiration(raw)
    return expires_at is not None and expires_at <= now


def _expired_trials(tenants: Mapping[str, object], *, now: datetime) -> dict[str, object]:
    """Return ``{tenant_id: raw_entry}`` of every expired trial in ``tenants``."""
    return {tenant_id: raw for tenant_id, raw in tenants.items() if _is_expired_trial(raw, now=now)}


def _active_trial_count(tenants: Mapping[str, object], *, now: datetime) -> int:
    return sum(
        1
        for raw in tenants.values()
        if isinstance(raw, Mapping) and raw.get("kind") == "trial" and not _is_expired_trial(raw, now=now)
    )


def _created_trial_count_for_day(tenants: Mapping[str, object], *, now: datetime) -> int:
    day = now.astimezone(UTC).date()
    count = 0
    for raw in tenants.values():
        if not isinstance(raw, Mapping) or raw.get("kind") != "trial":
            continue
        created_at = _parse_iso_datetime(raw.get("created_at"))
        if created_at is not None and created_at.date() == day:
            count += 1
    return count


def _prune_agent_bindings(agents_path: Path | None, tenant_ids: set[str]) -> None:
    if agents_path is None or not tenant_ids:
        return
    with _locked_json(agents_path) as agents:
        for tenant_id in tenant_ids:
            agents.pop(tenant_id, None)


PENDING_ERASURE_FILENAME = "pending-erasure.json"


def pending_erasure_path(tenants_path: Path) -> Path:
    """Sidecar ledger, next to the tenants file, of ids awaiting data erasure.

    Trial expiry cuts ACCESS immediately (the tenant is popped from tenants.json),
    but the tenant's on-disk data — ``juris.db``, artefatos, corpus chunks — is
    only actually deleted by ``juris tenant purge-expired``. This ledger is the
    *only* source of truth for that pending work: an id absent from tenants.json
    but not listed here must never be auto-erased (it could be operator error,
    not an expired trial).
    """
    return tenants_path.parent / PENDING_ERASURE_FILENAME


def _record_pending_erasure(tenants_path: Path, pruned: Mapping[str, object], *, now: datetime) -> None:
    """Merge trial ids slated for erasure into the pending-erasure ledger.

    Append-only merge: an id already on the ledger keeps its original entry (so
    recording the same id more than once is idempotent and never loses data
    already recorded there). The ledger holds no PII — only tenant ids and
    timestamps — but is chmod 600 to match compliance-erasure.jsonl's posture.
    """
    if not pruned:
        return
    ledger_path = pending_erasure_path(tenants_path)
    with _locked_json(ledger_path) as ledger:
        for tenant_id, raw in pruned.items():
            expires_at = None
            if isinstance(raw, Mapping):
                expires_at = raw.get("trial_expires_at") or raw.get("expires_at")
            ledger.setdefault(tenant_id, {"trial_expires_at": expires_at, "pruned_at": _iso(now)})
    restrict_file(ledger_path)


def read_pending_erasure(tenants_path: Path) -> dict[str, object]:
    """Read the pending-erasure ledger for the given tenants file (``{}`` if none)."""
    return _load_json_object(pending_erasure_path(tenants_path))


def remove_from_pending_erasure(tenants_path: Path, tenant_id: str) -> None:
    """Clear one tenant id from the pending-erasure ledger.

    Callers must only do this after a *successful* erasure (or after verifying
    the id is a stale leftover of an active tenant) — on failure the id should
    stay pending so the next run retries it.
    """
    ledger_path = pending_erasure_path(tenants_path)
    with _locked_json(ledger_path) as ledger:
        ledger.pop(tenant_id, None)
    restrict_file(ledger_path)


def is_tenant_active(tenants_path: Path, tenant_id: str, *, now: datetime) -> bool:
    """True if ``tenant_id`` is currently present in tenants.json and not an expired trial.

    Hard guard for automatic erasure: a tenant that is still active must never be
    erased, even if it (erroneously or maliciously) appears in the pending-erasure
    ledger.
    """
    raw = _load_json_object(tenants_path).get(tenant_id)
    if raw is None:
        return False
    if isinstance(raw, Mapping):
        return not _is_expired_trial(raw, now=now)
    return True  # legacy string-hash entries are always active accounts


def revoke_tenant_access(tenants_path: Path, tenant_id: str) -> bool:
    """Remove ``tenant_id`` from tenants.json so its API key(s) stop authenticating.

    Called as part of erasure (:func:`juris.ops.erasure.execute_tenant_erasure`) so
    an erased tenant's old key is rejected outright (401) instead of authenticating
    into an empty, freshly-wiped account. A no-op (returns ``False``) when the file
    doesn't exist — matching an open deployment with no tenants configured — or
    when the id is already absent (e.g. a trial already popped by
    :func:`sweep_expired_trials`); never creates the file.
    """
    tenant_id = validate_tenant_id(tenant_id)
    if not tenants_path.exists():
        return False
    removed = False
    with _locked_json(tenants_path) as tenants:
        if tenant_id in tenants:
            del tenants[tenant_id]
            removed = True
    if removed:
        _clear_auth_caches()
    return removed


def preview_expired_trials(tenants_path: Path, *, now: datetime | None = None) -> dict[str, object]:
    """Read-only: which trials in tenants.json a sweep would prune+enqueue right now.

    Used by ``purge-expired --dry-run`` so the preview matches what the next real
    run will actually do — without writing anything (no pop, no ledger entry).
    """
    return _expired_trials(_load_json_object(tenants_path), now=now or _utc_now())


def _sweep_ledger_first(tenants_path: Path, *, now: datetime) -> dict[str, object]:
    """Enqueue expired trials on the erasure ledger, THEN pop them from tenants.json.

    The ordering is deliberate crash-safety: the ledger entry is committed to disk
    *before* the tenants.json pop. If the process dies between the two writes, the
    id sits on the ledger while still listed in tenants.json — purge-expired then
    either re-sweeps it (still expired) or drops it as a stale ledger entry
    (active and non-expired). The reverse order would cut access first and, on a
    crash, orphan the tenant's data forever with no erasure record.

    Takes its own lock on ``tenants_path`` — never call it from inside an open
    ``_locked_json(tenants_path)`` block (same-process re-lock would deadlock).
    """
    candidates = _expired_trials(_load_json_object(tenants_path), now=now)
    if not candidates:
        return {}
    _record_pending_erasure(tenants_path, candidates, now=now)  # ledger FIRST
    popped: dict[str, object] = {}
    with _locked_json(tenants_path) as tenants:
        for tenant_id in candidates:
            raw = tenants.get(tenant_id)
            if raw is not None and _is_expired_trial(raw, now=now):
                popped[tenant_id] = raw
                tenants.pop(tenant_id, None)
    return popped


def sweep_expired_trials(
    *,
    tenants_path: Path,
    agents_path: Path | None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Prune any expired trials still listed in tenants.json and enqueue them for erasure.

    Belt-and-braces companion to the opportunistic pruning inside
    :func:`create_trial_access`: a trial that expires with no further trial signup
    afterwards would otherwise sit untouched in tenants.json indefinitely. The
    ledger entry is written before the tenants.json pop (see
    :func:`_sweep_ledger_first` for the crash-safety rationale).
    """
    now = now or _utc_now()
    pruned = _sweep_ledger_first(tenants_path, now=now)
    if pruned:
        _prune_agent_bindings(agents_path, set(pruned))
        _clear_auth_caches()
    return pruned


@contextmanager
def acquire_purge_lock(tenants_path: Path) -> Iterator[bool]:
    """Cross-process lock for a purge run; yields False if another purge holds it.

    Prevents an overlapping manual + scheduled ``purge-expired`` from racing
    ``rmtree`` on the same tenant. Non-blocking: the loser reports and exits
    instead of queueing behind a long erasure.
    """
    import fcntl

    lock_path = pending_erasure_path(tenants_path).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)  # releases the flock


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
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        restrict_file(path)
        with os.fdopen(fd, "r+", encoding="utf-8") as fh:
            fd = -1
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
    finally:
        if fd >= 0:
            os.close(fd)


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
    max_active = trial_max_active()
    max_new_per_day = trial_max_new_per_day()
    # Opportunistic prune, ledger-first (see _sweep_ledger_first): enqueue expired
    # trials for erasure BEFORE their tenants.json entries are popped.
    pruned_trials: dict[str, object] = _sweep_ledger_first(tenants_path, now=now)
    capacity_exceeded = False

    for _ in range(10):
        tenant_id = f"trial_{secrets.token_hex(8)}"
        api_key = f"causia_{secrets.token_urlsafe(32)}"
        agent_token = secrets.token_urlsafe(32)
        with _locked_json(tenants_path) as tenants:
            if max_new_per_day and _created_trial_count_for_day(tenants, now=now) >= max_new_per_day:
                capacity_exceeded = True
                break
            if _active_trial_count(tenants, now=now) >= max_active:
                capacity_exceeded = True
                break
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

    _prune_agent_bindings(agents_path, set(pruned_trials))
    if capacity_exceeded:
        _clear_auth_caches()
        msg = "limite de testes anônimos atingido."
        raise TrialCapacityError(msg)

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


def normalize_contact_email(email: str) -> str:
    """Normalize and validate an optional trial contact e-mail."""
    normalized = email.strip().lower()
    if len(normalized) > 254 or not _EMAIL_RE.fullmatch(normalized):
        msg = "e-mail inválido."
        raise ValueError(msg)
    return normalized


def update_trial_contact_email(
    tenant_id: str,
    email: str,
    *,
    tenants_path: Path | None = None,
) -> str:
    """Store an optional contact e-mail for trial expiry/recovery assistance."""
    tenant_id = validate_tenant_id(tenant_id)
    contact_email = normalize_contact_email(email)
    tenants_path = tenants_path or tenants_file_path()
    with _locked_json(tenants_path) as tenants:
        if tenant_id not in tenants:
            msg = f"tenant não encontrado: {tenant_id}"
            raise KeyError(msg)
        entry = _structured_tenant_entry(tenants[tenant_id], now=_utc_now())
        if entry.get("kind") != "trial":
            msg = "e-mail opcional está disponível apenas para testes anônimos."
            raise ValueError(msg)
        entry["contact_email"] = contact_email
        tenants[tenant_id] = entry
    return contact_email


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
        "contact_email": raw.get("contact_email") if isinstance(raw.get("contact_email"), str) else None,
        "keys": [
            {"id": key_id, "label": entry.get("label", key_id) if isinstance(entry, dict) else key_id}
            for key_id, entry in keys.items()
        ],
    }
