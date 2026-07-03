"""Production-readiness validator for a multi-tenant deployment (`juris doctor`).

The biggest operational risk isn't a missing feature — it's a *misconfiguration* that
silently drops the isolation/split-trust guarantees (open registry, plaintext API keys,
a remote tenant with no agent binding, world-readable secrets). These pure checks make
that visible before a firm's data is exposed.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_TRUTHY = {"1", "true", "yes"}


@dataclass(frozen=True, slots=True)
class Check:
    """One production-readiness check result."""

    name: str
    ok: bool
    detail: str
    severity: str = "error"  # "error" (blocks) | "warn" (should fix)


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUTHY


def _is_group_or_world_accessible(path: Path) -> bool:
    """True if others/group can read the file (secrets must be owner-only)."""
    mode = stat.S_IMODE(path.stat().st_mode)
    return bool(mode & 0o077)


def _load_tenant_keys(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = "JURIS_TENANTS_FILE deve conter um objeto JSON {tenant_id: api_key}."
        raise ValueError(msg)
    return data


def check_production_readiness(env: Mapping[str, str] | None = None) -> list[Check]:
    """Run every production-readiness check and return the results (order = report order)."""
    env = env if env is not None else os.environ
    checks: list[Check] = []

    # 1. Fail-closed multi-tenant posture. In prod, the runtime enforces this
    # even if JURIS_REQUIRE_TENANTS was forgotten.
    prod_env = env.get("ENVIRONMENT", "").strip().lower() == "prod"
    require = _flag(env, "JURIS_REQUIRE_TENANTS") or prod_env
    checks.append(
        Check(
            "require_tenants",
            require,
            "ENVIRONMENT=prod exige tenants"
            if prod_env and not _flag(env, "JURIS_REQUIRE_TENANTS")
            else "JURIS_REQUIRE_TENANTS=1"
            if require
            else "não definido — fallback ao tenant público é permitido",
        )
    )

    # 2. Tenants file present + non-empty (real registry, not open).
    tenants_path_str = env.get("JURIS_TENANTS_FILE")
    tenants_path = Path(tenants_path_str) if tenants_path_str else None
    tenant_keys: dict[str, object] = {}
    active_tenant_ids: tuple[str, ...] = ()
    if tenants_path is None:
        checks.append(Check("tenants_file", False, "JURIS_TENANTS_FILE não definido"))
    elif not tenants_path.exists():
        checks.append(Check("tenants_file", False, f"arquivo não encontrado: {tenants_path}"))
    else:
        try:
            tenant_keys = _load_tenant_keys(tenants_path)
        except (ValueError, OSError) as exc:
            checks.append(Check("tenants_file", False, f"ilegível: {exc}"))
        else:
            ok = len(tenant_keys) >= 1
            checks.append(
                Check("tenants_file", ok, f"{len(tenant_keys)} tenant(s) configurado(s)" if ok else "vazio")
            )

    # 3. API keys are hashed (never plaintext) AND pass the REAL registry validation
    #    (well-formed sha256, no duplicate keys, no reserved ids). Doctor must not accept
    #    a weaker model than TenantRegistry — a garbage hash / dup key would boot-crash.
    if tenant_keys:
        plaintext = _plaintext_key_entries(tenant_keys)
        if plaintext:
            checks.append(
                Check("hashed_keys", False, f"chaves em texto puro: {', '.join(plaintext)} — use hash-key")
            )
        else:
            try:
                from juris.web.auth import TenantRegistry

                registry = TenantRegistry(tenant_keys)
            except (ValueError, TypeError) as exc:
                checks.append(Check("hashed_keys", False, f"registro de tenants inválido: {exc}"))
            else:
                active_tenant_ids = registry.tenant_ids
                checks.append(Check("hashed_keys", True, "chaves hashadas e válidas (sha256:)"))

    # 4. Secrets files are owner-only (0600) — world/group-readable secrets BLOCK.
    for label, path in (("tenants_file_perms", tenants_path), ("agents_file_perms", _agents_path(env))):
        if path is not None and path.exists():
            accessible = _is_group_or_world_accessible(path)
            checks.append(
                Check(
                    label,
                    not accessible,
                    "permissões owner-only" if not accessible else f"{path} legível por grupo/outros — chmod 600",
                )
            )

    # 5. Agent posture: remote is the hosted-pilot target; in-process stays possible
    # for a truly co-located/local install, but doctor should make that explicit.
    agent_mode = env.get("JURIS_AGENT_MODE", "inprocess").strip().lower()
    checks.append(_check_agent_mode_posture(agent_mode, require))

    # 6. Remote agent mode: every tenant must have its own binding (no silent global fallback).
    if agent_mode == "remote":
        checks.extend(_check_remote_bindings(env, active_tenant_ids))

    # 7. Storage root is private.
    checks.append(_check_storage_private(env))

    # 8. Server-controlled output root.
    out_root = env.get("JURIS_OUT_ROOT")
    checks.append(
        Check(
            "out_root",
            bool(out_root),
            f"JURIS_OUT_ROOT={out_root}" if out_root else "não definido — usa caminho relativo 'juris-out'",
            severity="warn",
        )
    )

    # 9. Reverse-channel relay is in-memory unless the deploy asserts a safe topology.
    if agent_mode == "remote":
        checks.append(_check_reverse_channel_scaling(env))

    # 10. API rate-limit counters must be shared once the app has multiple workers.
    checks.append(_check_rate_limit_distribution(env))

    # 11. In production, audit logs need an HMAC key to anchor head/tail integrity.
    checks.append(_check_audit_hmac(env))

    return checks


def _agents_path(env: Mapping[str, str]) -> Path | None:
    p = env.get("JURIS_AGENTS_FILE")
    return Path(p) if p else None


def _check_agent_mode_posture(agent_mode: str, require_tenants: bool) -> Check:
    if agent_mode == "remote":
        return Check("agent_mode", True, "remote: token/PIN/PJe ficam no agente local")
    if agent_mode == "inprocess":
        if require_tenants:
            return Check(
                "agent_mode",
                False,
                "inprocess em deploy com tenants: só use em instalação local/co-localizada; "
                "para piloto hospedado use remote + JURIS_AGENTS_FILE",
                severity="warn",
            )
        return Check("agent_mode", True, "inprocess: aceitável em execução local sem tenants", severity="warn")
    return Check("agent_mode", False, f"JURIS_AGENT_MODE inválido: {agent_mode!r}")


def _plaintext_key_entries(tenant_keys: Mapping[str, object]) -> list[str]:
    plaintext: list[str] = []
    for tid, value in tenant_keys.items():
        if isinstance(value, str):
            if not value.startswith("sha256:"):
                plaintext.append(str(tid))
            continue
        if isinstance(value, Mapping):
            keys = value.get("keys")
            if not isinstance(keys, Mapping):
                continue
            for key_id, entry in keys.items():
                if isinstance(entry, str):
                    key_value = entry
                elif isinstance(entry, Mapping):
                    key_value = entry.get("hash") or entry.get("api_key")
                else:
                    continue
                if isinstance(key_value, str) and not key_value.startswith("sha256:"):
                    plaintext.append(f"{tid}/{key_id}")
    return plaintext


def _check_remote_bindings(env: Mapping[str, str], tenant_ids: tuple[str, ...]) -> list[Check]:
    agents_path = _agents_path(env)
    if agents_path is None:
        return [Check("agent_bindings", False, "JURIS_AGENT_MODE=remote exige JURIS_AGENTS_FILE")]
    if not agents_path.exists():
        return [Check("agent_bindings", False, f"JURIS_AGENTS_FILE não encontrado: {agents_path}")]
    try:
        bindings = _load_tenant_keys(agents_path)  # same {id: value} shape
    except (ValueError, OSError) as exc:
        return [Check("agent_bindings", False, f"JURIS_AGENTS_FILE ilegível: {exc}")]

    missing = [tid for tid in tenant_ids if tid not in bindings]
    incomplete = [
        tid
        for tid, b in bindings.items()
        if not (isinstance(b, dict) and b.get("url") and b.get("token"))
    ]
    # Cross-wired: two tenants must NOT share the same agent (a firm's A3-signed filings
    # routing to another firm's machine is a split-trust breach doctor previously missed).
    seen: dict[tuple[str, str], str] = {}
    crosswired: list[str] = []
    for tid, b in bindings.items():
        if isinstance(b, dict) and b.get("url") and b.get("token"):
            key = (str(b["url"]), str(b["token"]))
            if key in seen:
                crosswired.append(f"{tid}={seen[key]}")
            else:
                seen[key] = tid
    ok = not missing and not incomplete and not crosswired
    parts = []
    if missing:
        parts.append(f"sem binding: {', '.join(missing)}")
    if incomplete:
        parts.append(f"binding incompleto (precisa url+token): {', '.join(incomplete)}")
    if crosswired:
        parts.append(f"agente compartilhado entre tenants (cross-wired): {', '.join(crosswired)}")
    return [Check("agent_bindings", ok, "; ".join(parts) if parts else "todos os tenants têm agente próprio")]


def _check_storage_private(env: Mapping[str, str]) -> Check:
    home = Path(env["JURIS_HOME"]) if env.get("JURIS_HOME") else Path.home() / ".juris"
    if not home.exists():
        return Check("storage_private", True, f"{home} (será criado com 0700)", severity="warn")
    accessible = _is_group_or_world_accessible(home)
    return Check(
        "storage_private",
        not accessible,
        "storage owner-only" if not accessible else f"{home} legível por grupo/outros — chmod 700",
        severity="error",  # world/group-readable storage (every tenant's DB + receipts) must BLOCK
    )


def _configured_worker_count(env: Mapping[str, str]) -> tuple[int, bool]:
    """Return max configured worker count and whether any worker value was malformed."""
    workers = 1
    malformed = False
    for name in ("WEB_CONCURRENCY", "JURIS_WEB_WORKERS"):
        raw = env.get(name, "").strip()
        if not raw:
            continue
        try:
            workers = max(workers, int(raw))
        except ValueError:
            malformed = True
    return workers, malformed


def _check_reverse_channel_scaling(env: Mapping[str, str]) -> Check:
    workers, malformed = _configured_worker_count(env)
    if workers <= 1 and not malformed:
        return Check("reverse_channel_scaling", True, "single-worker ou sem escala horizontal")
    broker = bool(env.get("JURIS_RELAY_BROKER", "").strip())
    sticky = _flag(env, "JURIS_RELAY_STICKY")
    ok = broker or sticky
    if ok:
        detail = "broker configurado" if broker else "sticky routing declarado por JURIS_RELAY_STICKY=1"
    elif malformed:
        detail = "contagem de workers inválida; não dá para provar single-worker"
    else:
        detail = (
            "múltiplos workers sem JURIS_RELAY_BROKER nem JURIS_RELAY_STICKY=1; "
            "o canal reverso é process-local"
        )
    return Check("reverse_channel_scaling", ok, detail)


def _check_rate_limit_distribution(env: Mapping[str, str]) -> Check:
    workers, malformed = _configured_worker_count(env)
    if workers <= 1 and not malformed:
        return Check("rate_limit_distribution", True, "process-local OK em single-worker", severity="warn")
    redis_url = bool(env.get("JURIS_RATE_LIMIT_REDIS_URL", "").strip())
    proxy = _flag(env, "JURIS_RATE_LIMIT_PROXY")
    ok = redis_url or proxy
    if ok:
        detail = "Redis compartilhado" if redis_url else "rate limit declarado no reverse proxy"
    elif malformed:
        detail = (
            "contagem de workers inválida; configure JURIS_RATE_LIMIT_REDIS_URL "
            "ou declare JURIS_RATE_LIMIT_PROXY=1"
        )
    else:
        detail = (
            "múltiplos workers sem JURIS_RATE_LIMIT_REDIS_URL nem JURIS_RATE_LIMIT_PROXY=1; "
            "limite efetivo vira N_workers × limite"
        )
    return Check("rate_limit_distribution", ok, detail, severity="warn")


def _check_audit_hmac(env: Mapping[str, str]) -> Check:
    prod_env = env.get("ENVIRONMENT", "").strip().lower() == "prod"
    configured = bool(env.get("JURIS_AUDIT_HMAC_KEY", "").strip())
    if configured:
        return Check("audit_hmac_key", True, "JURIS_AUDIT_HMAC_KEY configurado")
    return Check(
        "audit_hmac_key",
        not prod_env,
        "ausente — audit.jsonl não terá âncora HMAC contra truncamento/recomputação",
        severity="error" if prod_env else "warn",
    )


def all_blocking_ok(checks: list[Check]) -> bool:
    """True when no ``error``-severity check failed (warns don't block)."""
    return all(c.ok for c in checks if c.severity == "error")
