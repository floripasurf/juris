"""Tests for shared diagnostic sanitizers."""

from __future__ import annotations

from juris.core.sanitize import safe_error_text


def test_safe_error_text_redacts_secrets_paths_documents_and_credentialed_urls() -> None:
    text = safe_error_text(
        RuntimeError(
            "mTLS /Users/adv/a3 token=abc pin=1234 senha=segredo "
            "Authorization: Bearer abc 076.710.396-32 12345678909 "
            "CNPJ 11222333000181 CNJ 50823514020178130024 "
            "email autor@example.test em 01/02/2026 "
            "https://user:pass@example.test/x ordinary=12345678901"
        )
    )

    assert "token=abc" not in text
    assert "pin=1234" not in text
    assert "senha=segredo" not in text
    assert "Bearer abc" not in text
    assert "076.710.396-32" not in text
    assert "12345678909" not in text
    assert "11222333000181" not in text
    assert "50823514020178130024" not in text
    assert "autor@example.test" not in text
    assert "01/02/2026" not in text
    assert "/Users/adv/a3" not in text
    assert "user:pass@" not in text
    assert "ordinary=12345678901" in text
    assert "token=<redacted>" in text
    assert "pin=<redacted>" in text
    assert "senha=<redacted>" in text
    assert "Authorization: <redacted>" in text
    assert "<cpf>" in text
    assert "<cnpj>" in text
    assert "<cnj>" in text
    assert "<email>" in text
    assert "<data>" in text
    assert "<local-path>" in text
