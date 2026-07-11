"""Fixture factories for MNI avisos (intimações) responses."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


def make_aviso(
    id_aviso: str = "AV001",
    tipo: str = "intimacao",
    numero_processo: str = "5082351-40.2017.8.13.0024",
    data_disponibilizacao: datetime | None = None,
    data_limite: datetime | None = None,
    orgao: str = "5ª Vara Cível de BH",
) -> SimpleNamespace:
    return SimpleNamespace(
        idAviso=id_aviso,
        tipoComunicacao=tipo,
        numeroProcesso=numero_processo,
        dataDisponibilizacao=data_disponibilizacao or datetime(2026, 4, 28, 10, 0),
        dataLimiteCiencia=data_limite or datetime(2026, 5, 5, 23, 59),
        orgaoJulgador=orgao,
    )


def make_avisos_response(avisos: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    """Fixture for consultarAvisosPendentes response with avisos."""
    return SimpleNamespace(
        sucesso=True,
        mensagem="",
        aviso=avisos or [
            make_aviso("AV001", "intimacao", "5082351-40.2017.8.13.0024"),
            make_aviso("AV002", "citacao", "5080938-89.2017.8.13.0024",
                       data_disponibilizacao=datetime(2026, 4, 29, 8, 0)),
        ],
    )


def make_avisos_response_empty() -> SimpleNamespace:
    return SimpleNamespace(sucesso=True, mensagem="", aviso=[])


def make_avisos_response_error() -> SimpleNamespace:
    return SimpleNamespace(sucesso=False, mensagem="Falha de autenticação", aviso=None)


def make_teor_response(conteudo: str = "Fica V.Sa. intimado(a) para manifestação no prazo de 15 dias.") -> SimpleNamespace:  # noqa: E501
    return SimpleNamespace(
        sucesso=True,
        mensagem="",
        comunicacao=SimpleNamespace(conteudo=conteudo),
    )


def make_teor_response_error() -> SimpleNamespace:
    return SimpleNamespace(sucesso=False, mensagem="Aviso não encontrado", comunicacao=None)
