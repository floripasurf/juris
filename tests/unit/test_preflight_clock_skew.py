"""Clock skew do preflight: mede contra o header Date do tribunal, warning-only.

Skew grande reprova o check como AVISO (não bloqueia o filing, pois só severity
'blocker' com passed=False bloqueia — ver run_preflight). Tribunal ausente ou
inacessível degrada para o comportamento anterior (passa com aviso).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from juris.signing.preflight import _check_clock_skew, run_preflight


def _patch_head(monkeypatch: pytest.MonkeyPatch, server_now: datetime | None, *, fail: bool = False) -> None:
    def fake_head(url: str, **kwargs: object) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("down")
        headers = {"Date": format_datetime(server_now)} if server_now else {}
        return httpx.Response(200, headers=headers)

    monkeypatch.setattr("juris.signing.preflight.httpx.head", fake_head)


def test_skew_pequeno_passa(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_head(monkeypatch, datetime.now(UTC) + timedelta(seconds=5))
    check = _check_clock_skew("https://mni.exemplo.jus.br/ws")
    assert check.name == "clock_skew"
    assert check.passed is True
    assert check.severity == "warning"


def test_skew_grande_gera_warning_reprovado(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_head(monkeypatch, datetime.now(UTC) + timedelta(seconds=600))
    check = _check_clock_skew("https://mni.exemplo.jus.br/ws")
    assert check.passed is False
    assert check.severity == "warning"  # avisa, mas não bloqueia
    assert "skew" in check.message.lower() or "relógio" in check.message.lower()


def test_sem_url_mantem_comportamento_atual() -> None:
    check = _check_clock_skew(None)
    assert check.passed is True
    assert check.severity == "warning"


def test_tribunal_inacessivel_nao_bloqueia(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_head(monkeypatch, None, fail=True)
    check = _check_clock_skew("https://mni.exemplo.jus.br/ws")
    assert check.passed is True
    assert "indispon" in check.message.lower()


def test_header_date_ausente_nao_bloqueia(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_head(monkeypatch, None)  # resposta 200 sem header Date
    check = _check_clock_skew("https://mni.exemplo.jus.br/ws")
    assert check.passed is True


def test_run_preflight_com_skew_grande_ainda_passa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um skew grande é aviso: o preflight não deve reprovar por causa dele."""
    _patch_head(monkeypatch, datetime.now(UTC) + timedelta(seconds=600))
    # PDF mínimo válido (%PDF header) evita blockers de PDF.
    pdf = b"%PDF-1.4\n%%EOF\n"
    result = run_preflight(
        numero_cnj="0001234-56.2024.8.13.0024",
        tribunal="tjmg",
        tipo_documento="peticao",
        pdf_bytes=pdf,
        tribunal_url="https://mni.exemplo.jus.br/ws",
    )
    skew = next(c for c in result.checks if c.name == "clock_skew")
    assert skew.passed is False
    assert skew not in result.blockers
