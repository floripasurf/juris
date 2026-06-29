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
from typing import TYPE_CHECKING

from juris.core.observability import get_logger
from juris.escavacao.executor import InteiroTeor

if TYPE_CHECKING:
    from juris.escavacao.queue import AlvoEscavacao

logger = get_logger(__name__)

_LICENSE = "dados públicos TST (jurisprudencia.tst.jus.br)"
# Isolated selectors — retune against a real TST sample, not the fixture.
_PRIMARY_SELECTORS = (".ementa", ".acordao")  # the decision blocks, accumulated
_FALLBACK_SELECTORS = (".documento",)  # whole-document container, if the blocks are absent
_CHROME_SELECTORS = ("nav", ".navbar", "header", "footer", "script", "style")

FetchHtml = Callable[[str], "str | None"]


def _default_fetch_html(numero_cnj: str) -> str | None:
    """Fetch the TST acórdão HTML for a CNJ (public endpoint, gentle, no bypass)."""
    import httpx

    url = tst_url(numero_cnj)
    try:
        resp = httpx.get(url, timeout=10.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.warning("tst_fetch_failed", numero_cnj=numero_cnj, error=str(exc))
        return None
    if resp.status_code != 200:
        logger.warning("tst_fetch_status", numero_cnj=numero_cnj, status=resp.status_code)
        return None
    return resp.text


def tst_url(numero_cnj: str) -> str:
    """The public TST jurisprudence URL for a CNJ (provenance)."""
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
