"""Tests for core value objects."""

import pytest

from juris.core.types import NumeroCNJ, TenantId


class TestNumeroCNJ:
    def test_valid_cnj_number(self) -> None:
        cnj = NumeroCNJ("0009999-99.2024.8.26.0001")
        assert str(cnj) == "0009999-99.2024.8.26.0001"

    def test_invalid_cnj_number(self) -> None:
        with pytest.raises(ValueError, match="Invalid CNJ number format"):
            NumeroCNJ("invalid")

    def test_invalid_cnj_missing_parts(self) -> None:
        with pytest.raises(ValueError):
            NumeroCNJ("0009999-99.2024")

    def test_cnj_justica_code(self) -> None:
        cnj = NumeroCNJ("0009999-99.2024.8.26.0001")
        assert cnj.justica == "8"

    def test_cnj_tribunal_code(self) -> None:
        cnj = NumeroCNJ("0009999-99.2024.8.26.0001")
        assert cnj.tribunal == "26"

    def test_cnj_origem_code(self) -> None:
        cnj = NumeroCNJ("0009999-99.2024.8.26.0001")
        assert cnj.origem == "0001"

    def test_cnj_is_frozen(self) -> None:
        cnj = NumeroCNJ("0009999-99.2024.8.26.0001")
        with pytest.raises(AttributeError):
            cnj.value = "other"  # type: ignore[misc]


class TestTenantId:
    def test_valid_tenant(self) -> None:
        t = TenantId("firm-123")
        assert str(t) == "firm-123"

    def test_empty_tenant_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            TenantId("")
