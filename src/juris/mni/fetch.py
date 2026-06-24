"""Unified MNI processo fetch — single entry point for mTLS and password paths.

Both the overnight sync job and the demo pipeline need to read a processo via
MNI. Tribunals split into two auth families:

* **mTLS** (e.g. TJMG): the WSDL is only reachable with an ICP-Brasil client
  certificate, so we authenticate with the A3 hardware token over PKCS#11.
* **password** (zeep): a CPF + PJe password pair sent in the SOAP body.

:func:`fetch_processo_mni` resolves the right path from the tribunal config and
returns a :class:`ProcessoDomain`, so callers never branch on auth themselves.
It is a pure library function: credentials (CPF, PJe password, token PIN) are
passed in already resolved — it never prompts.
"""

from __future__ import annotations

from urllib.parse import urlparse

from juris.core.observability import get_logger
from juris.mni.parsers.processo import ProcessoDomain
from juris.mni.tribunais import TribunalConfig

logger = get_logger(__name__)


def fetch_processo_mni(
    numero_cnj: str,
    tribunal_cfg: TribunalConfig,
    cpf: str,
    senha: str,
    *,
    token_pin: str | None = None,
    com_documentos: bool = False,
) -> ProcessoDomain:
    """Fetch a processo via MNI, choosing mTLS or password auth automatically.

    Args:
        numero_cnj: Case number in CNJ format.
        tribunal_cfg: Tribunal configuration (decides the auth path).
        cpf: Consultant CPF (idConsultante).
        senha: PJe application password (senhaConsultante).
        token_pin: A3 token PIN; falls back to ``settings.token_pin`` when None
            (mTLS path only). Ignored on the password path.
        com_documentos: Include full document content in the response.

    Returns:
        The fetched :class:`ProcessoDomain`.

    Raises:
        RuntimeError: On MNI-level failure, or when an mTLS tribunal has no
            available token PIN.
    """
    if tribunal_cfg.requires_mtls:
        return _fetch_mtls(
            numero_cnj=numero_cnj,
            tribunal_cfg=tribunal_cfg,
            cpf=cpf,
            senha=senha,
            token_pin=token_pin,
            com_documentos=com_documentos,
        )
    return _fetch_password(
        numero_cnj=numero_cnj,
        tribunal_cfg=tribunal_cfg,
        cpf=cpf,
        senha=senha,
        com_documentos=com_documentos,
    )


def _fetch_mtls(
    *,
    numero_cnj: str,
    tribunal_cfg: TribunalConfig,
    cpf: str,
    senha: str,
    token_pin: str | None,
    com_documentos: bool,
) -> ProcessoDomain:
    """Fetch from an mTLS tribunal via the A3 token (PKCS#11)."""
    from juris.config import get_settings
    from juris.mni.operations.consulta_pkcs11 import consultar_processo_pkcs11
    from juris.mni.token import build_pkcs11_config, extract_token_material

    settings = get_settings()
    pin = token_pin or (settings.token_pin.get_secret_value() if settings.token_pin else None)
    if not pin:
        msg = "mTLS tribunal requires a token PIN (pass --pin or set TOKEN_PIN)."
        raise RuntimeError(msg)

    material = extract_token_material(settings.pkcs11_module)
    pkcs11_config = build_pkcs11_config(material, pin, settings.pkcs11_module)

    service_url = tribunal_cfg.service_url_override or tribunal_cfg.wsdl_url.replace("?wsdl", "")
    parsed = urlparse(service_url)

    result = consultar_processo_pkcs11(
        host=parsed.hostname or "",
        path=parsed.path or "/pje/intercomunicacao",
        pkcs11_config=pkcs11_config,
        id_consultante=cpf,
        senha_consultante=senha,
        numero_cnj=numero_cnj,
        mni_version=tribunal_cfg.mni_version,
        com_documentos=com_documentos,
    )
    if not result.sucesso:
        msg = f"MNI error: {result.mensagem}"
        raise RuntimeError(msg)

    return result.to_processo_domain(tribunal_id=tribunal_cfg.id, numero_cnj=numero_cnj)


def _fetch_password(
    *,
    numero_cnj: str,
    tribunal_cfg: TribunalConfig,
    cpf: str,
    senha: str,
    com_documentos: bool,
) -> ProcessoDomain:
    """Fetch from a password-auth tribunal via the zeep SOAP client."""
    from juris.mni.auth import PasswordAuth
    from juris.mni.client import get_mni_client
    from juris.mni.operations.consulta import consultar_processo
    from juris.mni.parsers.processo import parse_processo

    auth = PasswordAuth(cpf=cpf, senha=senha)
    client = get_mni_client(tribunal_cfg.id, auth)
    response = consultar_processo(
        client=client,
        id_consultante=cpf,
        senha_consultante=senha,
        numero_cnj=numero_cnj,
        com_documentos=com_documentos,
    )
    if getattr(response, "sucesso", None) is False:
        msg = f"MNI error: {getattr(response, 'mensagem', 'Unknown error')}"
        raise RuntimeError(msg)

    return parse_processo(response, tribunal_id=tribunal_cfg.id)
