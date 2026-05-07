"""Spec-driven tests for the pre-flight checker module.

Spec Requirements Covered
=========================

Source: ADR-0011 (docs/architecture-decisions/0011-pades-filing.md)
Source: mni_integration_reference.md §2.5 (failure modes)

| ID    | Spec clause                              | Scenario                                              |
|-------|------------------------------------------|-------------------------------------------------------|
| PF-1  | ADR §9: dry-run executes all preflight   | run_preflight returns all checks populated             |
| PF-2  | ADR §5: only TJMG and TRT-2 in scope    | tipo_documento valid for tjmg/trt2; unknown warns      |
| PF-3  | Ref §2.5: "Documento corrompido"         | PDF missing %PDF header → blocker                     |
| PF-4  | Ref §2.5: "Documento corrompido"         | Empty PDF → blocker                                   |
| PF-5  | Ref §2.5: tribunal doc type vocabulary   | Invalid tipo_documento → blocker with accepted list    |
| PF-6  | ADR §10: prazo override allows filing    | Expired prazo + override → passes with warning         |
| PF-7  | ADR §10: prazo override mandatory        | Expired prazo + no override → blocker                  |
| PF-8  | Ref §2.5: "Erro de assinatura" expired   | Expired cert → blocker                                |
| PF-9  | Ref §2.5: cert expiring soon             | Cert valid but <30d → warning (not blocker)            |
| PF-10 | ADR §9: preflight is side-effect-free    | No external calls, no state mutation                   |
| PF-11 | General: all pass                        | All checks pass → passed=True, empty blockers          |
| PF-12 | General: multiple blockers collected     | Multiple failures → all collected, not short-circuited |
| PF-13 | ADR §5: PDF size limit                   | PDF >10MB → blocker                                   |
| PF-14 | General: clock skew placeholder          | clock_skew check present in result                     |
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from juris.signing.preflight import (
    CertStatus,
    PrazoStatus,
    run_preflight,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

MINIMAL_PDF = b"%PDF-1.4 minimal"


@dataclass(frozen=True)
class _MockPrazo:
    dias_uteis_restantes: int


@dataclass(frozen=True)
class _MockPrazoReport:
    numero_cnj: str = "0000000-00.0000.0.00.0000"
    tribunal: str = "tjmg"
    computed_at: date = date.today()
    prazos: list[_MockPrazo] | None = None

    def __post_init__(self) -> None:
        if self.prazos is None:
            object.__setattr__(self, "prazos", [])


def _make_prazo_report(dias: int) -> _MockPrazoReport:
    """Create a prazo report with a single prazo at the given days remaining."""
    return _MockPrazoReport(prazos=[_MockPrazo(dias_uteis_restantes=dias)])


def _valid_cert(days_ahead: int = 365) -> CertStatus:
    """Certificate that is valid for ``days_ahead`` from today."""
    return CertStatus(
        valid=True,
        cn="ADVOGADO TESTE:12345678901",
        cpf="12345678901",
        valid_until=date.today() + timedelta(days=days_ahead),
        pin_attempts_remaining=None,
    )


def _expired_cert() -> CertStatus:
    """Certificate whose valid_until is in the past."""
    return CertStatus(
        valid=True,
        cn="ADVOGADO TESTE:12345678901",
        cpf="12345678901",
        valid_until=date.today() - timedelta(days=1),
        pin_attempts_remaining=None,
    )


def _invalid_cert() -> CertStatus:
    """Certificate flagged invalid (e.g. revoked by the CA)."""
    return CertStatus(
        valid=False,
        cn="ADVOGADO TESTE:12345678901",
        cpf="12345678901",
        valid_until=date.today() + timedelta(days=365),
        pin_attempts_remaining=None,
        error="Revogado pela AC",
    )


def _check_names(result: object) -> list[str]:
    """Extract check names from a PreflightResult."""
    return [c.name for c in result.checks]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# PF-3, PF-4, PF-13 — PDF checks
# ---------------------------------------------------------------------------


class TestPreflightPdfChecks:
    """PDF validity, header, and size limit checks."""

    def test_empty_pdf_is_blocker(self) -> None:
        """PF-4: Empty PDF bytes must be a blocker."""
        result = run_preflight("123", "tjmg", "peticao", b"")
        assert not result.passed
        assert "pdf_not_empty" in [b.name for b in result.blockers]

    def test_invalid_pdf_header_is_blocker(self) -> None:
        """PF-3: Bytes not starting with %PDF must be a blocker."""
        result = run_preflight("123", "tjmg", "peticao", b"NOT-A-PDF-FILE")
        assert not result.passed
        assert "pdf_valid" in [b.name for b in result.blockers]

    def test_oversized_pdf_is_blocker(self) -> None:
        """PF-13: PDF exceeding 10 MB tribunal limit must be a blocker."""
        big_pdf = b"%PDF-1.4" + b"\x00" * (10 * 1024 * 1024 + 1)
        result = run_preflight("123", "tjmg", "peticao", big_pdf)
        assert not result.passed
        assert "pdf_size_limit" in [b.name for b in result.blockers]

    def test_valid_small_pdf_passes(self) -> None:
        """PF-11 (partial): Valid PDF with no other issues passes preflight."""
        result = run_preflight("123", "tjmg", "peticao", MINIMAL_PDF)
        assert result.passed


# ---------------------------------------------------------------------------
# PF-2, PF-5 — Tipo documento / tribunal scope
# ---------------------------------------------------------------------------


class TestPreflightTipoDocumento:
    """Tribunal vocabulary and scope checks."""

    def test_invalid_tipo_documento_is_blocker(self) -> None:
        """PF-5: Tipo not in tribunal vocabulary is a blocker."""
        result = run_preflight("123", "tjmg", "habeas_corpus", MINIMAL_PDF)
        assert not result.passed
        assert "tipo_documento_valid" in [b.name for b in result.blockers]

    def test_valid_tipo_documento_tjmg(self) -> None:
        """PF-2: contestacao is in TJMG vocabulary."""
        result = run_preflight("123", "tjmg", "contestacao", MINIMAL_PDF)
        assert result.passed

    def test_valid_tipo_documento_trt2(self) -> None:
        """PF-2: recurso_ordinario is in TRT-2 vocabulary (not in TJMG)."""
        result = run_preflight("123", "trt2", "recurso_ordinario", MINIMAL_PDF)
        assert result.passed

    def test_trt2_specific_tipo_not_in_tjmg(self) -> None:
        """PF-2: TRT-2-only tipo is a blocker when filed at TJMG."""
        result = run_preflight("123", "tjmg", "recurso_ordinario", MINIMAL_PDF)
        assert not result.passed
        assert "tipo_documento_valid" in [b.name for b in result.blockers]

    def test_unknown_tribunal_warns_but_passes(self) -> None:
        """PF-2: Unknown tribunal has no vocabulary — warn, don't block."""
        result = run_preflight("123", "tjba", "qualquer_tipo", MINIMAL_PDF)
        assert result.passed
        tipo_checks = [c for c in result.checks if c.name == "tipo_documento_valid"]
        assert len(tipo_checks) == 1
        assert tipo_checks[0].severity == "warning"
        assert tipo_checks[0].passed


# ---------------------------------------------------------------------------
# PF-8, PF-9 — Certificate checks
# ---------------------------------------------------------------------------


class TestPreflightCertChecks:
    """Certificate validity and expiry warning checks."""

    def test_invalid_cert_is_blocker(self) -> None:
        """PF-8: Revoked/invalid certificate is a blocker."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            cert_status=_invalid_cert(),
        )
        assert not result.passed
        assert "cert_valid" in [b.name for b in result.blockers]

    def test_expired_cert_is_blocker(self) -> None:
        """PF-8: Certificate past valid_until is a blocker."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            cert_status=_expired_cert(),
        )
        assert not result.passed
        assert "cert_valid" in [b.name for b in result.blockers]

    def test_valid_cert_passes(self) -> None:
        """PF-11 (partial): Valid cert does not block."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            cert_status=_valid_cert(),
        )
        assert result.passed

    def test_cert_expiring_within_30_days_is_warning(self) -> None:
        """PF-9: Cert valid but <30 days left emits warning, not blocker."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            cert_status=_valid_cert(days_ahead=15),
        )
        assert result.passed
        expiry_checks = [c for c in result.checks if c.name == "cert_expiring_soon"]
        assert len(expiry_checks) == 1
        assert expiry_checks[0].severity == "warning"

    def test_cert_at_31_days_no_warning(self) -> None:
        """PF-9 boundary: Cert at exactly 31 days does not emit warning."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            cert_status=_valid_cert(days_ahead=31),
        )
        assert result.passed
        expiry_checks = [c for c in result.checks if c.name == "cert_expiring_soon"]
        assert len(expiry_checks) == 0


# ---------------------------------------------------------------------------
# PF-6, PF-7 — Prazo checks
# ---------------------------------------------------------------------------


class TestPreflightPrazo:
    """Deadline status and override checks."""

    def test_safe_prazo_passes(self) -> None:
        """PF-11 (partial): >5 days remaining is safe."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            prazo_report=_make_prazo_report(dias=10),
        )
        assert result.passed
        assert result.prazo_status == PrazoStatus.SAFE

    def test_urgent_prazo_is_warning(self) -> None:
        """2-5 days remaining is urgent — warning, not blocker."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            prazo_report=_make_prazo_report(dias=3),
        )
        assert result.passed
        assert result.prazo_status == PrazoStatus.URGENT
        prazo_checks = [c for c in result.checks if c.name == "prazo_status"]
        assert len(prazo_checks) == 1
        assert prazo_checks[0].severity == "warning"

    def test_expiring_prazo_is_warning(self) -> None:
        """<2 days remaining is expiring — warning, not blocker."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            prazo_report=_make_prazo_report(dias=1),
        )
        assert result.passed
        assert result.prazo_status == PrazoStatus.EXPIRING
        prazo_checks = [c for c in result.checks if c.name == "prazo_status"]
        assert len(prazo_checks) == 1
        assert prazo_checks[0].severity == "warning"

    def test_expired_prazo_is_blocker(self) -> None:
        """PF-7: Expired prazo without override is a blocker."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            prazo_report=_make_prazo_report(dias=-2),
        )
        assert not result.passed
        assert result.prazo_status == PrazoStatus.EXPIRED
        assert "prazo_status" in [b.name for b in result.blockers]

    def test_expired_prazo_with_override_passes(self) -> None:
        """PF-6: Expired prazo + justificativa override downgrades to warning."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            prazo_report=_make_prazo_report(dias=-2),
            prazo_override="Justa causa comprovada",
        )
        assert result.passed
        assert result.prazo_status == PrazoStatus.EXPIRED
        prazo_checks = [c for c in result.checks if c.name == "prazo_status"]
        assert len(prazo_checks) == 1
        assert prazo_checks[0].severity == "warning"

    def test_unknown_prazo_passes(self) -> None:
        """Empty prazo report results in UNKNOWN status — no blocker."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            prazo_report=_MockPrazoReport(),
        )
        assert result.passed
        assert result.prazo_status == PrazoStatus.UNKNOWN


# ---------------------------------------------------------------------------
# PF-1, PF-10, PF-11, PF-12, PF-14 — Integrated / aggregation
# ---------------------------------------------------------------------------


class TestPreflightIntegrated:
    """Aggregation, side-effect safety, and completeness checks."""

    def test_all_checks_populated(self) -> None:
        """PF-1: run_preflight returns result with all check categories populated."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            cert_status=_valid_cert(),
            prazo_report=_make_prazo_report(dias=10),
        )
        names = _check_names(result)
        # Must include at least pdf, tipo_documento, cert, and clock_skew checks
        assert "pdf_not_empty" in names
        assert "pdf_valid" in names
        assert "pdf_size_limit" in names
        assert "tipo_documento_valid" in names
        assert "cert_valid" in names
        assert "clock_skew" in names

    def test_clock_skew_placeholder_present(self) -> None:
        """PF-14: clock_skew check always included in result."""
        result = run_preflight("123", "tjmg", "peticao", MINIMAL_PDF)
        clock_checks = [c for c in result.checks if c.name == "clock_skew"]
        assert len(clock_checks) == 1
        assert clock_checks[0].passed  # Placeholder passes

    def test_all_pass_happy_path(self) -> None:
        """PF-11: All valid inputs → passed=True, zero blockers."""
        result = run_preflight(
            "123", "tjmg", "peticao", MINIMAL_PDF,
            cert_status=_valid_cert(),
            prazo_report=_make_prazo_report(dias=10),
        )
        assert result.passed
        assert len(result.blockers) == 0

    def test_warnings_do_not_block(self) -> None:
        """PF-11: Multiple warnings (unknown tribunal, expiring cert, urgent prazo)
        still result in passed=True."""
        result = run_preflight(
            "123", "tjba", "qualquer_tipo", MINIMAL_PDF,
            cert_status=_valid_cert(days_ahead=15),
            prazo_report=_make_prazo_report(dias=3),
        )
        assert result.passed
        assert len(result.blockers) == 0
        warnings = [c for c in result.checks if c.severity == "warning"]
        assert len(warnings) > 0

    def test_multiple_blockers_all_collected(self) -> None:
        """PF-12: Multiple failures are all collected, not short-circuited."""
        # Invalid PDF header + invalid tipo + expired cert → at least 3 blockers
        result = run_preflight(
            "123", "tjmg", "habeas_corpus", b"NOT-A-PDF",
            cert_status=_invalid_cert(),
        )
        assert not result.passed
        blocker_names = [b.name for b in result.blockers]
        assert "pdf_valid" in blocker_names
        assert "tipo_documento_valid" in blocker_names
        assert "cert_valid" in blocker_names
        assert len(result.blockers) >= 3

    def test_no_side_effects(self) -> None:
        """PF-10: run_preflight is pure — calling twice with same args gives same result,
        and it does not mutate any external state."""
        args = ("123", "tjmg", "peticao", MINIMAL_PDF)
        kwargs = {"cert_status": _valid_cert(), "prazo_report": _make_prazo_report(dias=10)}

        result_1 = run_preflight(*args, **kwargs)
        result_2 = run_preflight(*args, **kwargs)

        assert result_1.passed == result_2.passed
        assert len(result_1.checks) == len(result_2.checks)
        assert [c.name for c in result_1.checks] == [c.name for c in result_2.checks]
        assert [c.passed for c in result_1.checks] == [c.passed for c in result_2.checks]
