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


def test_full_inprocess_prod_config_passes(tmp_path) -> None:
    from juris.web.auth import hash_api_key

    tenants = _write_tenants(tmp_path, {"escritorio-a": hash_api_key("secret-a")})
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
