"""MNI read service — the boundary between the orchestrator and the token (ADR-0015).

The A3 token is non-exportable hardware, so an MNI read (mTLS handshake) must run
on the machine where the token is plugged in. Callers (demo pipeline, web
orchestrator) depend on the :class:`MNIReadService` abstraction instead of
importing the PKCS#11 / mTLS machinery directly. Two implementations are
foreseen:

* :class:`InProcessMNIReadService` — runs the read in the current process
  (Phase 1, token co-located with the app). This is the only implementation
  today; it wraps :func:`juris.mni.fetch.fetch_processo_mni`.
* A future ``RemoteMNIReadService`` — forwards the read to the lawyer's local
  agent over the authenticated localhost protocol (Phase 2, multi-tenant).

Swapping implementations is configuration, not a rewrite of the orchestrator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from juris.mni.parsers.processo import ProcessoDomain
from juris.mni.tribunais import TribunalConfig

if TYPE_CHECKING:
    from juris.mni.operations.intimacoes import AvisosResult


class MNIReadService(ABC):
    """Reads from MNI (processos + avisos), abstracting where the token lives."""

    @abstractmethod
    def consultar_processo(
        self,
        numero_cnj: str,
        tribunal_cfg: TribunalConfig,
        cpf: str,
        senha: str,
        *,
        token_pin: str | None = None,
        com_documentos: bool = False,
    ) -> ProcessoDomain:
        """Read a processo, choosing mTLS or password auth from ``tribunal_cfg``.

        Args:
            numero_cnj: Case number in CNJ format.
            tribunal_cfg: Tribunal configuration (decides the auth path).
            cpf: Consultant CPF (idConsultante).
            senha: PJe application password (senhaConsultante).
            token_pin: A3 token PIN (mTLS tribunals); resolved by the caller.
            com_documentos: Include full document content.

        Returns:
            The fetched :class:`ProcessoDomain`.

        Raises:
            RuntimeError: On MNI-level failure or missing token PIN.
        """
        ...

    @abstractmethod
    def consultar_avisos(
        self,
        tribunal_cfg: TribunalConfig,
        cpf: str,
        senha: str,
        *,
        token_pin: str | None = None,
    ) -> AvisosResult:
        """Read pending avisos (intimações) — the live-deadline feed.

        Args:
            tribunal_cfg: Tribunal configuration (decides the auth path).
            cpf: Consultant CPF (idConsultante).
            senha: PJe application password (senhaConsultante).
            token_pin: A3 token PIN (mTLS tribunals); resolved by the caller.

        Returns:
            An ``AvisosResult`` (``sucesso=False`` on MNI-level error).

        Raises:
            RuntimeError: On missing token PIN for an mTLS tribunal.
        """
        ...


class InProcessMNIReadService(MNIReadService):
    """Runs the MNI read in the current process (Phase 1, co-located token)."""

    def consultar_processo(
        self,
        numero_cnj: str,
        tribunal_cfg: TribunalConfig,
        cpf: str,
        senha: str,
        *,
        token_pin: str | None = None,
        com_documentos: bool = False,
    ) -> ProcessoDomain:
        # Lazy import keeps the PKCS#11 / zeep deps out of the import graph of
        # callers that only hold the abstraction.
        from juris.mni.fetch import fetch_processo_mni

        return fetch_processo_mni(
            numero_cnj,
            tribunal_cfg,
            cpf,
            senha,
            token_pin=token_pin,
            com_documentos=com_documentos,
        )

    def consultar_avisos(
        self,
        tribunal_cfg: TribunalConfig,
        cpf: str,
        senha: str,
        *,
        token_pin: str | None = None,
    ) -> AvisosResult:
        from juris.mni.fetch import fetch_avisos_mni

        return fetch_avisos_mni(tribunal_cfg, cpf, senha, token_pin=token_pin)
