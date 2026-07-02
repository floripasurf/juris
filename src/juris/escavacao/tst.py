"""TST inteiro-teor adapter — the first real full-text source (frente C).

TST publishes its jurisprudence openly (``jurisprudencia.tst.jus.br``) and is the
one portal automatable without a WAF/captcha fight, so it is the first source
plugged ahead of DataJud in the :class:`FailoverFetcher`. We **never** bypass a
WAF or captcha: when the page can't be fetched or parsed, the fetcher returns
``None`` and the mesh falls back to the DataJud trail.

The selectors below are isolated and validated against a realistic fixture; a
real-sample smoke test (``docs/`` runbook) retunes them against live TST HTML.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from juris.config import get_settings
from juris.core.observability import get_logger
from juris.core.sanitize import safe_error_text
from juris.escavacao.executor import InteiroTeor

if TYPE_CHECKING:
    from juris.escavacao.queue import AlvoEscavacao

logger = get_logger(__name__)

_LICENSE = "dados públicos TST (jurisprudencia.tst.jus.br)"
_BACKEND_URL = "https://jurisprudencia-backend2.tst.jus.br/rest/pesquisa-textual"
# Isolated selectors — retune against a real TST sample, not the fixture.
_PRIMARY_SELECTORS = (".ementa", ".acordao")  # the decision blocks, accumulated
_FALLBACK_SELECTORS = (".documento",)  # whole-document container, if the blocks are absent
_CHROME_SELECTORS = ("nav", ".navbar", "header", "footer", "script", "style")

FetchHtml = Callable[[str], "str | None"]


def _default_fetch_html(numero_cnj: str) -> str | None:
    """Fetch the TST acórdão HTML for a CNJ via the public JSON backend.

    The SPA URL contains ``#/`` and does not deliver rendered content to HTTP
    clients. The backend endpoint is the same public one used by the TST search
    page. It remains gated by config until ToS is explicitly approved.
    """
    import httpx

    if not get_settings().tst_inteiro_teor_enabled:
        logger.info("tst_fetch_gated", numero_cnj=numero_cnj)
        return None

    url = f"{_BACKEND_URL}/1/3"
    try:
        resp = httpx.post(
            url,
            json=tst_backend_search_body(numero_cnj),
            timeout=20.0,
            headers={"User-Agent": "Juris/0.1"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("tst_fetch_failed", numero_cnj=numero_cnj, error=safe_error_text(exc))
        return None
    return extract_tst_backend_html(resp.json(), numero_cnj)


def tst_backend_search_body(numero_cnj: str) -> dict[str, Any]:
    """Build the public TST search payload for one CNJ."""
    return {
        "e": _unpadded_cnj(numero_cnj),
        "ou": "",
        "termoExato": "",
        "naoContem": "",
        "ementa": "",
        "dispositivo": "",
        "tipos": [
            {
                "codigo": "ACORDAO",
                "value": "acordaos",
                "codMin": "",
                "checked": True,
                "label": "Acórdãos",
                "qtdRegistros": 0,
            }
        ],
        "orgaosJudicantes": [],
        "ministros": [],
        "convocados": [],
        "classesProcessuais": [],
        "indicadores": [],
        "assuntos": [],
    }


def extract_tst_backend_html(payload: dict[str, Any], numero_cnj: str) -> str | None:
    """Extract the best full-text HTML field from a TST backend payload."""
    target_digits = _normalize_cnj_digits(numero_cnj)
    for wrapper in payload.get("registros", []):
        item = wrapper.get("registro", {}) if isinstance(wrapper, dict) else {}
        if not isinstance(item, dict):
            continue
        if target_digits and not _record_matches_cnj(item, target_digits):
            continue
        html = _first_nonempty(
            item,
            "inteiroTeorHtml",
            "inteiroTeorHTMLHighlight",
            "txtEmentaHighlight",
            "ementaHtml",
            "ementa",
        )
        if not html or _is_backend_redacted(html):
            continue
        return f'<div class="documento">{html}</div>'
    return None


def _first_nonempty(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _record_matches_cnj(item: dict[str, Any], target_digits: str) -> bool:
    values: list[str] = []
    for key in ("numero", "numProcDocumento", "numFormatado"):
        value = item.get(key)
        if value is not None:
            values.append(str(value))
    numeracao_unica = item.get("numeracaoUnica")
    if isinstance(numeracao_unica, dict):
        values.extend(str(v) for v in numeracao_unica.values() if v is not None)
    return any(_normalize_cnj_digits(value) == target_digits for value in values)



def _unpadded_cnj(numero_cnj: str) -> str:
    """CNJ sem zeros à esquerda no sequencial — o índice do TST só casa assim."""
    import re

    match = re.search(r"(\d{1,7})-(\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})", numero_cnj.strip())
    if not match:
        return numero_cnj.strip()
    seq = match.group(1).lstrip("0") or "0"
    return f"{seq}-{match.group(2)}"


def _normalize_cnj_digits(value: str) -> str:
    import re

    text = value.strip()
    match = re.search(r"(\d{1,7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})", text)
    if match:
        seq, digit, year, justice, tribunal, origin = match.groups()
        return f"{seq.zfill(7)}{digit}{year}{justice}{tribunal}{origin}"
    digits = re.sub(r"\D", "", text)
    if len(digits) == 20:
        return digits
    if len(digits) in {18, 19}:
        return digits.zfill(20)
    return digits


def _is_backend_redacted(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped in {"removido no backend", "removida no backend"}


def _is_probable_decision_text(text: str) -> bool:
    normalized = " ".join(text.upper().split())
    if len(normalized) < 200:
        return False
    markers = ("A C Ó R D Ã O", "ACÓRDÃO", "ACORDAO", "EMENTA", "RECURSO DE REVISTA")
    return any(marker in normalized for marker in markers)


def tst_detail_url(doc_id: str) -> str:
    """The public SPA detail URL for a TST document id."""
    return f"https://jurisprudencia.tst.jus.br/#/detalhe-documento/{doc_id}"


def tst_url(numero_cnj: str) -> str:
    """The public TST jurisprudence URL for a CNJ (provenance/search page)."""
    return f"https://jurisprudencia.tst.jus.br/#/{numero_cnj}"


def parse_tst_acordao(html: str) -> str | None:
    """Extract the decision text (ementa + acórdão) from a TST page, or None.

    Strips page chrome and tags; returns ``None`` when no decision block is found
    (a login wall, error page, or empty result), so the caller can fall back.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for selector in _CHROME_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    blocks: list[str] = []
    for selector in _PRIMARY_SELECTORS:  # accumulate ementa + acórdão together
        for node in soup.select(selector):
            text = node.get_text(separator=" ", strip=True)
            if text:
                blocks.append(text)

    if not blocks:  # neither block found → fall back to the document container
        for selector in _FALLBACK_SELECTORS:
            for node in soup.select(selector):
                text = node.get_text(separator=" ", strip=True)
                if text:
                    blocks.append(text)

    if not blocks:
        body_text = soup.get_text(separator=" ", strip=True)
        if _is_probable_decision_text(body_text):
            blocks.append(body_text)

    if not blocks:
        return None
    combined = "\n".join(dict.fromkeys(blocks))  # dedup repeated nodes, keep order
    return combined or None


class TSTEscavacaoFetcher:
    """Fetches the full acórdão from TST (``parcial=False``); the moat's first real source."""

    def __init__(self, *, fetch_html: FetchHtml | None = None, today: str | None = None) -> None:
        self._fetch_html = fetch_html or _default_fetch_html
        self._today = today

    async def fetch(self, alvo: AlvoEscavacao) -> InteiroTeor | None:
        import asyncio

        html = await asyncio.to_thread(self._fetch_html, alvo.numero_cnj)
        if not html:
            return None
        texto = parse_tst_acordao(html)
        if not texto:
            return None
        return InteiroTeor(
            numero_cnj=alvo.numero_cnj,
            texto=texto,
            fonte="tst",
            origem_tema=alvo.origem_tema,
            parcial=False,  # the real acórdão, not a movements trail
            url=tst_url(alvo.numero_cnj),
            licenca=_LICENSE,
            data_coleta=self._today,
        )
