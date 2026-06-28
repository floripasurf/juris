"""Tests for tenant authentication (multi-tenant foundation — Track 5)."""

from __future__ import annotations

import pytest

from juris.web.auth import Tenant, TenantRegistry, resolve_tenant


def test_open_when_no_tenants_configured() -> None:
    registry = TenantRegistry({})
    assert registry.is_open is True
    # an open deployment resolves everyone to the shared public tenant
    assert resolve_tenant(registry, api_key=None) == Tenant("public")


def test_valid_api_key_resolves_its_tenant() -> None:
    registry = TenantRegistry({"escritorio-a": "key-aaa", "escritorio-b": "key-bbb"})
    assert resolve_tenant(registry, api_key="key-bbb") == Tenant("escritorio-b")


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
