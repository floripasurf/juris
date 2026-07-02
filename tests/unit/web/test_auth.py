"""Tests for tenant authentication (multi-tenant foundation — Track 5)."""

from __future__ import annotations

import pytest

from juris.web.auth import Tenant, TenantRegistry, require_tenants_enabled, resolve_tenant


def test_open_when_no_tenants_configured() -> None:
    registry = TenantRegistry({})
    assert registry.is_open is True
    # an open deployment resolves everyone to the shared public tenant
    assert resolve_tenant(registry, api_key=None) == Tenant("public")


def test_prod_environment_requires_tenants_even_without_flag() -> None:
    registry = TenantRegistry({})
    assert require_tenants_enabled({"ENVIRONMENT": "prod"}) is True
    with pytest.raises(PermissionError, match="tenants exigidos"):
        resolve_tenant(registry, api_key=None, require_configured=require_tenants_enabled({"ENVIRONMENT": "prod"}))


def test_valid_api_key_resolves_its_tenant() -> None:
    registry = TenantRegistry({"escritorio-a": "key-aaa", "escritorio-b": "key-bbb"})
    assert resolve_tenant(registry, api_key="key-bbb") == Tenant("escritorio-b")
    assert registry.tenant_ids == ("escritorio-a", "escritorio-b")


def test_missing_or_invalid_key_is_rejected_when_configured() -> None:
    registry = TenantRegistry({"escritorio-a": "key-aaa"})
    assert registry.is_open is False
    with pytest.raises(PermissionError):
        resolve_tenant(registry, api_key=None)
    with pytest.raises(PermissionError):
        resolve_tenant(registry, api_key="wrong")


def test_from_file_loads_tenant_keys(tmp_path) -> None:
    import json

    path = tmp_path / "tenants.json"
    path.write_text(json.dumps({"escritorio-a": "key-aaa"}), encoding="utf-8")
    registry = TenantRegistry.from_file(path)
    assert resolve_tenant(registry, api_key="key-aaa") == Tenant("escritorio-a")


def test_from_file_missing_is_open(tmp_path) -> None:
    registry = TenantRegistry.from_file(tmp_path / "does-not-exist.json")
    assert registry.is_open is True


def test_tenant_scoped_dir_isolates_non_public(tmp_path) -> None:
    from juris.web.auth import tenant_scoped_dir

    assert tenant_scoped_dir(Tenant("public"), tmp_path) == tmp_path
    assert tenant_scoped_dir(Tenant("escritorio-a"), tmp_path) == tmp_path / "tenants" / "escritorio-a"


def test_tenant_db_path_isolates(tmp_path) -> None:
    from juris.web.auth import tenant_db_path

    assert tenant_db_path(Tenant("public"), base=tmp_path) == tmp_path / "juris.db"
    assert (
        tenant_db_path(Tenant("escritorio-a"), base=tmp_path)
        == tmp_path / "tenants" / "escritorio-a" / "juris.db"
    )


def test_tenant_db_path_default_honors_juris_home(tmp_path, monkeypatch) -> None:
    from juris.web.auth import tenant_db_path

    monkeypatch.setenv("JURIS_HOME", str(tmp_path))

    assert tenant_db_path(Tenant("public")) == tmp_path / "juris.db"
    assert tenant_db_path(Tenant("escritorio-a")) == tmp_path / "tenants" / "escritorio-a" / "juris.db"


def test_authenticates_hashed_keys_for_production() -> None:
    from juris.web.auth import hash_api_key

    registry = TenantRegistry({"escritorio-a": hash_api_key("raw-key")})
    assert resolve_tenant(registry, api_key="raw-key") == Tenant("escritorio-a")
    with pytest.raises(PermissionError):
        resolve_tenant(registry, api_key="wrong")


def test_rejects_unsafe_tenant_id_in_config() -> None:
    with pytest.raises(ValueError, match="inválido"):
        TenantRegistry({"../etc": "key"})


def test_validate_tenant_id_rejects_unsafe_runtime_ids() -> None:
    from juris.web.auth import validate_tenant_id

    assert validate_tenant_id("escritorio-a_1") == "escritorio-a_1"
    with pytest.raises(ValueError, match="inválido"):
        validate_tenant_id("../escape")


def test_rejects_reserved_public_tenant_id_in_config() -> None:
    with pytest.raises(ValueError, match="reservado"):
        TenantRegistry({"public": "key"})


def test_rejects_empty_api_key_in_config() -> None:
    with pytest.raises(ValueError, match="API key inválida"):
        TenantRegistry({"escritorio-a": ""})


def test_rejects_api_key_with_edge_spaces_in_config() -> None:
    with pytest.raises(ValueError, match="espaços"):
        TenantRegistry({"escritorio-a": " key "})


def test_rejects_malformed_hashed_api_key_in_config() -> None:
    with pytest.raises(ValueError, match="sha256"):
        TenantRegistry({"escritorio-a": "sha256:not-a-valid-hex-digest"})


def test_rejects_duplicate_api_key_in_config() -> None:
    with pytest.raises(ValueError, match="duplicada"):
        TenantRegistry({"escritorio-a": "same-key", "escritorio-b": "same-key"})


def test_from_file_rejects_non_object_json(tmp_path) -> None:
    import json

    path = tmp_path / "tenants.json"
    path.write_text(json.dumps(["not", "a", "map"]), encoding="utf-8")
    with pytest.raises(ValueError, match="objeto JSON"):
        TenantRegistry.from_file(path)


def test_tenant_scoped_dir_rejects_unsafe_id(tmp_path) -> None:
    from juris.web.auth import tenant_scoped_dir

    with pytest.raises(ValueError, match="inválido"):
        tenant_scoped_dir(Tenant("../escape"), tmp_path)


# --- #3: explicit sha256: hash format ---


def test_hash_api_key_is_prefixed() -> None:
    from juris.web.auth import hash_api_key

    assert hash_api_key("raw-key").startswith("sha256:")


def test_plaintext_key_not_confused_with_hash() -> None:
    from juris.web.auth import hash_api_key

    # a stored hash authenticates its raw key, and only that key
    registry = TenantRegistry({"a": hash_api_key("raw-key"), "b": "plain-key"})
    assert resolve_tenant(registry, api_key="raw-key") == Tenant("a")
    assert resolve_tenant(registry, api_key="plain-key") == Tenant("b")


# --- #1: fail-closed when tenants are required but absent ---


def test_open_registry_fails_closed_when_required() -> None:
    registry = TenantRegistry({})  # open
    with pytest.raises(PermissionError):
        resolve_tenant(registry, api_key=None, require_configured=True)


def test_open_registry_stays_open_by_default() -> None:
    registry = TenantRegistry({})
    assert resolve_tenant(registry, api_key=None) == Tenant("public")
