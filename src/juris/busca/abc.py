"""Abstract base class for search channels."""

from __future__ import annotations

from abc import ABC, abstractmethod

from juris.busca.models import FonteOrigem, ResultadoBusca


class SearchChannel(ABC):
    """Abstract search channel — one per tribunal system type.

    All methods are async so the orchestrator can call them
    concurrently via asyncio.gather.
    """

    @property
    @abstractmethod
    def channel_name(self) -> FonteOrigem:
        """Return the channel's FonteOrigem identifier."""

    @abstractmethod
    def supported_tribunais(self) -> list[str]:
        """Return list of tribunal IDs this channel can query."""

    @abstractmethod
    async def search_by_name(
        self, tribunal_id: str, nome: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by party name."""

    @abstractmethod
    async def search_by_cpf(
        self, tribunal_id: str, cpf: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by CPF/CNPJ document number."""

    @abstractmethod
    async def search_by_oab(
        self, tribunal_id: str, oab: str, max_results: int = 20
    ) -> list[ResultadoBusca]:
        """Search by OAB registration number."""
