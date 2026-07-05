"""Tests for the production-readiness validator (`juris doctor`)."""

from __future__ import annotations

import json

from juris.ops.production import check_production_readiness


def _by_name(checks):
    return {c.name: c for c in checks}


def _write_tenants(tmp_path, keys: dict[str, str]):
    p = tmp_path / "tenants.json"
    p.write_text(json.dumps(keys), encoding="utf-8")
    return p


def test_require_tenants_unset_is_an_error(tmp_path) -> None:
    checks = check_production_readiness(env={"JURIS_HOME": str(tmp_path)})
    c = _by_name(checks)["require_tenants"]
    assert c.ok is False
    assert c.severity == "error"


def test_prod_environment_enforces_tenant_requirement(tmp_path) -> None:
    checks = _by_name(check_production_readiness(env={"ENVIRONMENT": "prod", "JURIS_HOME": str(tmp_path)}))
    assert checks["require_tenants"].ok is True
    assert "ENVIRONMENT=prod" in checks["require_tenants"].detail
    assert checks["tenants_file"].ok is False
    assert checks["audit_hmac_key"].ok is False
    assert checks["audit_hmac_key"].severity == "error"


def test_audit_hmac_is_warn_only_outside_prod(tmp_path) -> None:
    checks = _by_name(check_production_readiness(env={"JURIS_HOME": str(tmp_path)}))
    assert checks["audit_hmac_key"].ok is True
    assert checks["audit_hmac_key"].severity == "warn"


def test_backend_urls_dev_default_in_prod_is_warn_not_block(tmp_path) -> None:
    checks = _by_name(check_production_readiness(env={"ENVIRONMENT": "prod", "JURIS_HOME": str(tmp_path)}))
    c = checks["backend_urls"]
    assert c.ok is True  # não bloqueia o piloto SQLite-first
    assert c.severity == "warn"
    assert "database_url" in c.detail


def test_backend_urls_dev_default_in_prod_strict_blocks(tmp_path) -> None:
    checks = _by_name(
        check_production_readiness(
            env={"ENVIRONMENT": "prod", "JURIS_HOME": str(tmp_path), "JURIS_STRICT_PROD_URLS": "1"}
        )
    )
    c = checks["backend_urls"]
    assert c.ok is False
    assert c.severity == "error"


def test_backend_urls_overridden_in_prod_passes(tmp_path) -> None:
    checks = _by_name(
        check_production_readiness(
            env={
                "ENVIRONMENT": "prod",
                "JURIS_HOME": str(tmp_path),
                "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/j",
                "DATABASE_URL_SYNC": "postgresql+psycopg://u:p@db:5432/j",
                "QDRANT_URL": "http://qdrant:6333",
                "REDIS_URL": "redis://redis:6379/0",
                "OLLAMA_URL": "http://ollama:11434",
            }
        )
    )
    c = checks["backend_urls"]
    assert c.ok is True
    assert "sobrescritas" in c.detail


def test_full_inprocess_prod_config_passes(tmp_path) -> None:
    import os

    from juris.web.auth import hash_api_key

    tenants = _write_tenants(tmp_path, {"escritorio-a": hash_api_key("secret-a")})
    os.chmod(tenants, 0o600)  # secure config: owner-only secrets + storage
    os.chmod(tmp_path, 0o700)
    env = {
        "JURIS_REQUIRE_TENANTS": "1",
        "JURIS_TENANTS_FILE": str(tenants),
        "JURIS_AGENT_MODE": "inprocess",
        "JURIS_HOME": str(tmp_path),
        "JURIS_OUT_ROOT": str(tmp_path / "out"),
    }
    checks = check_production_readiness(env=env)
    errors = [c for c in checks if c.severity == "error" and not c.ok]
    assert errors == [], f"unexpected errors: {[(c.name, c.detail) for c in errors]}"
    agent_mode = _by_name(checks)["agent_mode"]
    assert agent_mode.ok is False
    assert agent_mode.severity == "warn"


def test_plaintext_api_key_is_flagged(tmp_path) -> None:
    tenants = _write_tenants(tmp_path, {"escritorio-a": "plaintext-not-hashed"})
    env = {
        "JURIS_REQUIRE_TENANTS": "1",
        "JURIS_TENANTS_FILE": str(tenants),
        "JURIS_HOME": str(tmp_path),
    }
    c = _by_name(check_production_readiness(env=env))["hashed_keys"]
    assert c.ok is False
    assert c.severity == "error"


def test_remote_mode_requires_agents_file_with_bindings(tmp_path) -> None:
    from juris.web.auth import hash_api_key

    tenants = _write_tenants(tmp_path, {"escritorio-a": hash_api_key("k")})
    env = {
        "JURIS_REQUIRE_TENANTS": "1",
        "JURIS_TENANTS_FILE": str(tenants),
        "JURIS_AGENT_MODE": "remote",  # no JURIS_AGENTS_FILE → binding for escritorio-a missing
        "JURIS_HOME": str(tmp_path),
    }
    c = _by_name(check_production_readiness(env=env))["agent_bindings"]
    assert c.ok is False


def _blocking_errors(checks):
    return {c.name for c in checks if c.severity == "error" and not c.ok}


def test_world_readable_secrets_and_storage_block(tmp_path) -> None:
    import os

    from juris.web.auth import hash_api_key

    tenants = _write_tenants(tmp_path, {"a": hash_api_key("k")})
    os.chmod(tenants, 0o644)  # world-readable secrets  # noqa: S103
    os.chmod(tmp_path, 0o755)  # world-readable storage  # noqa: S103
    env = {"JURIS_REQUIRE_TENANTS": "1", "JURIS_TENANTS_FILE": str(tenants), "JURIS_HOME": str(tmp_path)}
    errors = _blocking_errors(check_production_readiness(env=env))
    assert "tenants_file_perms" in errors  # was warn-only
    assert "storage_private" in errors  # inverted-severity bug


def test_garbage_hash_and_duplicate_keys_block(tmp_path) -> None:
    from juris.web.auth import hash_api_key

    # garbage sha256 value
    bad = _write_tenants(tmp_path, {"a": "sha256:NOT_A_REAL_HASH"})
    assert "hashed_keys" in _blocking_errors(check_production_readiness(
        env={"JURIS_REQUIRE_TENANTS": "1", "JURIS_TENANTS_FILE": str(bad), "JURIS_HOME": str(tmp_path)}
    ))
    # two tenants sharing one key
    dup_key = hash_api_key("same")
    dup = _write_tenants(tmp_path, {"a": dup_key, "b": dup_key})
    assert "hashed_keys" in _blocking_errors(check_production_readiness(
        env={"JURIS_REQUIRE_TENANTS": "1", "JURIS_TENANTS_FILE": str(dup), "JURIS_HOME": str(tmp_path)}
    ))


def test_cross_wired_agent_binding_blocks(tmp_path) -> None:
    import json

    from juris.web.auth import hash_api_key

    tenants = _write_tenants(tmp_path, {"acme": hash_api_key("ka"), "globex": hash_api_key("kg")})
    agents = tmp_path / "agents.json"
    # globex's binding is IDENTICAL to acme's — globex filings would route to acme's agent
    shared = {"url": "wss://acme:8765", "token": "tok-acme"}
    agents.write_text(json.dumps({"acme": shared, "globex": shared}), encoding="utf-8")
    env = {
        "JURIS_REQUIRE_TENANTS": "1", "JURIS_TENANTS_FILE": str(tenants),
        "JURIS_AGENT_MODE": "remote", "JURIS_AGENTS_FILE": str(agents), "JURIS_HOME": str(tmp_path),
    }
    assert "agent_bindings" in _blocking_errors(check_production_readiness(env=env))


def test_remote_multiworker_without_sticky_or_broker_blocks(tmp_path) -> None:
    import os

    from juris.web.auth import hash_api_key

    tenants = _write_tenants(tmp_path, {"acme": hash_api_key("ka")})
    os.chmod(tenants, 0o600)
    agents = tmp_path / "agents.json"
    agents.write_text(json.dumps({"acme": {"url": "wss://acme.example/ws", "token": "tok"}}), encoding="utf-8")
    os.chmod(agents, 0o600)
    env = {
        "JURIS_REQUIRE_TENANTS": "1",
        "JURIS_TENANTS_FILE": str(tenants),
        "JURIS_AGENT_MODE": "remote",
        "JURIS_AGENTS_FILE": str(agents),
        "JURIS_HOME": str(tmp_path / "home"),
        "WEB_CONCURRENCY": "4",
    }

    checks = check_production_readiness(env=env)

    assert "reverse_channel_scaling" in _blocking_errors(checks)
    assert _by_name(checks)["rate_limit_distribution"].ok is False
    assert _by_name(checks)["rate_limit_distribution"].severity == "warn"


def test_remote_multiworker_with_sticky_and_redis_passes_scaling_checks(tmp_path) -> None:
    import os

    from juris.web.auth import hash_api_key

    tenants = _write_tenants(tmp_path, {"acme": hash_api_key("ka")})
    os.chmod(tenants, 0o600)
    agents = tmp_path / "agents.json"
    agents.write_text(json.dumps({"acme": {"url": "wss://acme.example/ws", "token": "tok"}}), encoding="utf-8")
    os.chmod(agents, 0o600)
    env = {
        "JURIS_REQUIRE_TENANTS": "1",
        "JURIS_TENANTS_FILE": str(tenants),
        "JURIS_AGENT_MODE": "remote",
        "JURIS_AGENTS_FILE": str(agents),
        "JURIS_HOME": str(tmp_path / "home"),
        "WEB_CONCURRENCY": "4",
        "JURIS_RELAY_STICKY": "1",
        "JURIS_RATE_LIMIT_REDIS_URL": "redis://localhost:6379/0",
    }

    checks = _by_name(check_production_readiness(env=env))

    assert checks["reverse_channel_scaling"].ok is True
    assert checks["rate_limit_distribution"].ok is True
