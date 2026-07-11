"""Registry of tribunal WSDL endpoints and configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SistemaProcessual(StrEnum):
    PJE = "pje"
    ESAJ = "esaj"
    EPROC = "eproc"
    PROJUDI = "projudi"


@dataclass(frozen=True, slots=True)
class TribunalConfig:
    """Configuration for a single tribunal's MNI endpoint."""

    id: str
    nome: str
    sistema: SistemaProcessual
    wsdl_url: str
    mni_version: str = "2.2.2"
    requires_envelope_signing: bool = False
    certificate_auth_supported: bool = True
    password_auth_supported: bool = True
    service_url_override: str | None = None  # Override SOAP endpoint (e.g. TJMG consulta-publica)
    requires_mtls: bool = False  # WSDL only reachable with an ICP-Brasil client cert (mTLS)


# Initial registry — expand as tribunals are tested
TRIBUNAL_REGISTRY: dict[str, TribunalConfig] = {
    "trt2": TribunalConfig(
        id="trt2",
        nome="TRT 2a Regiao - Sao Paulo",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.trt2.jus.br/pje/intercomunicacao?wsdl",
    ),
    "trt15": TribunalConfig(
        id="trt15",
        nome="TRT 15a Regiao - Campinas",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.trt15.jus.br/pje/intercomunicacao?wsdl",
    ),
    "trf3": TribunalConfig(
        id="trf3",
        nome="TRF 3a Regiao - SP/MS",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.trf3.jus.br/pje/intercomunicacao?wsdl",
    ),
    "trt1": TribunalConfig(
        id="trt1",
        nome="TRT 1a Regiao - Rio de Janeiro",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.trt1.jus.br/pje/intercomunicacao?wsdl",
    ),
    "tst": TribunalConfig(
        id="tst",
        nome="Tribunal Superior do Trabalho",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.tst.jus.br/pje/intercomunicacao?wsdl",
    ),
    "tjdf": TribunalConfig(
        id="tjdf",
        nome="TJDFT - Distrito Federal",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.tjdft.jus.br/pje/intercomunicacao?wsdl",
    ),
    "tjrj": TribunalConfig(
        id="tjrj",
        nome="TJRJ - Rio de Janeiro",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.tjrj.jus.br/pje/intercomunicacao?wsdl",
    ),
    "tjmg": TribunalConfig(
        id="tjmg",
        nome="TJMG - Minas Gerais",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje-consulta-publica.tjmg.jus.br/pje/intercomunicacao?wsdl",
        mni_version="2.2.3",
        service_url_override="https://pje-consulta-publica.tjmg.jus.br/pje/intercomunicacao",
        requires_mtls=True,  # validated 2026-06-12: WSDL 302s away without client cert
    ),
    # --- Confirmed working (WSDL accessible, no mTLS required) ---
    "tjes": TribunalConfig(
        id="tjes",
        nome="TJES - Espirito Santo",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.tjes.jus.br/pje/intercomunicacao?wsdl",
    ),
    "tjmt": TribunalConfig(
        id="tjmt",
        nome="TJMT - Mato Grosso",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.tjmt.jus.br/pje/intercomunicacao?wsdl",
    ),
    "tjpa": TribunalConfig(
        id="tjpa",
        nome="TJPA - Para",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.tjpa.jus.br/pje/intercomunicacao?wsdl",
    ),
    "tjpe": TribunalConfig(
        id="tjpe",
        nome="TJPE - Pernambuco",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.tjpe.jus.br/pje/intercomunicacao?wsdl",
    ),
    "trf5": TribunalConfig(
        id="trf5",
        nome="TRF 5a Regiao - PE/AL/SE/RN/PB/CE",
        sistema=SistemaProcessual.PJE,
        wsdl_url="https://pje.trf5.jus.br/pje/intercomunicacao?wsdl",
    ),
}


def get_tribunal(tribunal_id: str) -> TribunalConfig:
    """Look up a tribunal by ID. Raises KeyError if not found."""
    tribunal_id = tribunal_id.lower().strip()
    if tribunal_id not in TRIBUNAL_REGISTRY:
        available = ", ".join(sorted(TRIBUNAL_REGISTRY.keys()))
        msg = f"Tribunal '{tribunal_id}' not found. Available: {available}"
        raise KeyError(msg)
    return TRIBUNAL_REGISTRY[tribunal_id]


def list_tribunais() -> list[TribunalConfig]:
    """Return all registered tribunals."""
    return list(TRIBUNAL_REGISTRY.values())
