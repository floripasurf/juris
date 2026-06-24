"""Signing service — the boundary between the orchestrator and the token (ADR-0015).

PAdES signing uses the A3 token's private key, which never leaves the device,
so signing must run where the token is plugged in. Callers depend on the
:class:`SigningService` abstraction instead of constructing :class:`PAdESSigner`
directly. Two implementations are foreseen:

* :class:`InProcessSigningService` — signs in the current process (Phase 1,
  token co-located). Wraps :class:`juris.signing.pades.PAdESSigner`.
* A future ``RemoteSigningService`` — forwards the PDF to the lawyer's local
  agent over the authenticated WebSocket ``/ws/sign`` endpoint (Phase 2). The
  ``SignRequest``/``SignResponse`` schemas in ``juris.api.ws_schemas`` already
  describe that contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from juris.signing.pades import SigningResult


class SigningService(ABC):
    """Signs a PDF with the lawyer's A3 token, abstracting where it lives."""

    @abstractmethod
    def sign_pdf(
        self,
        pdf_bytes: bytes,
        *,
        pin: str,
        token_label: str | None = None,
        field_name: str = "AdvogadoSignature",
        use_timestamp: bool = False,
    ) -> SigningResult:
        """Sign ``pdf_bytes`` (PAdES) and return the signed PDF + metadata.

        Args:
            pdf_bytes: The unsigned PDF content.
            pin: A3 token PIN, resolved by the caller (never prompted here).
            token_label: PKCS#11 token label; resolved from the connected token
                when omitted.
            field_name: Signature field name.
            use_timestamp: Use the PAdES-T profile (timestamped) when True.

        Returns:
            A :class:`SigningResult`.

        Raises:
            RuntimeError: If the token/cert is unavailable.
        """
        ...


class InProcessSigningService(SigningService):
    """Signs in the current process (Phase 1, co-located token)."""

    def sign_pdf(
        self,
        pdf_bytes: bytes,
        *,
        pin: str,
        token_label: str | None = None,
        field_name: str = "AdvogadoSignature",
        use_timestamp: bool = False,
    ) -> SigningResult:
        # Lazy import keeps PKCS#11 / pyhanko out of the import graph of callers
        # that only hold the abstraction.
        from juris.config import get_settings
        from juris.mni.token import extract_token_material
        from juris.signing.pades import PAdESSigner

        settings = get_settings()
        label = token_label or extract_token_material(settings.pkcs11_module).token_label
        with PAdESSigner(settings.pkcs11_module, label, pin, use_timestamp=use_timestamp) as signer:
            return signer.sign(pdf_bytes, field_name=field_name)
