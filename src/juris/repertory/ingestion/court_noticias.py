"""Ingester for court news via RSS feeds.

Parses RSS feeds from STF, STJ, and TST to build a news corpus.
Deduplicates by URL; does not store full article HTML.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import feedparser  # type: ignore[import-untyped]

from juris.repertory.chunking import DocumentChunk, chunk_fonte
from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.base import CorpusIngester

logger = logging.getLogger(__name__)

RSS_FEEDS: dict[str, str] = {
    "STF": "https://portal.stf.jus.br/servicos/rss/",
    "STJ": "https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias/rss",
    "TST": "https://www.tst.jus.br/web/guest/noticias?rss=true",
}


class CourtNoticiasIngester(CorpusIngester):
    """Ingests court news items from RSS feeds.

    Fetches RSS from STF, STJ, and TST; deduplicates by entry URL;
    converts each news item into a FonteJurisprudencia.
    tipo: NOTICIA_TRIBUNAL, hierarquia: 7.

    Args:
        feeds: Mapping of tribunal key to RSS URL.
               Defaults to RSS_FEEDS (STF, STJ, TST).
        limit: Maximum number of items to ingest per feed (None for all).
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        feeds: dict[str, str] | None = None,
        limit: int | None = None,
        timeout: int = 20,
    ) -> None:
        self._feeds = feeds or RSS_FEEDS
        self._limit = limit
        self._timeout = timeout

    def fetch(self) -> list[FonteJurisprudencia]:
        """Fetch and parse RSS feeds, deduplicating by URL.

        Returns:
            List of FonteJurisprudencia, one per unique news item.
        """
        fontes: list[FonteJurisprudencia] = []
        seen_urls: set[str] = set()

        for tribunal, feed_url in self._feeds.items():
            items = self._fetch_feed(tribunal, feed_url)
            added = 0
            for item in items:
                if self._limit is not None and added >= self._limit:
                    break
                url = item.get("link", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                fonte = self._entry_to_fonte(tribunal, item)
                if fonte is not None:
                    fontes.append(fonte)
                    added += 1

        logger.info("Fetched %d court news items from %d feeds", len(fontes), len(self._feeds))
        return fontes

    def parse(self, raw: Any) -> list[DocumentChunk]:
        """Parse a FonteJurisprudencia into document chunks.

        Args:
            raw: A FonteJurisprudencia instance.

        Returns:
            List of document chunks.
        """
        if not isinstance(raw, FonteJurisprudencia):
            return []
        return chunk_fonte(raw)

    def _fetch_feed(self, tribunal: str, url: str) -> list[dict[str, Any]]:
        """Download and parse a single RSS feed.

        Args:
            tribunal: Court identifier (for logging).
            url: RSS feed URL.

        Returns:
            List of entry dicts from feedparser.
        """
        try:
            parsed = feedparser.parse(url, request_headers={"Connection": "close"})
        except Exception:
            logger.warning("Failed to parse RSS feed for %s: %s", tribunal, url, exc_info=True)
            return []

        if parsed.bozo and parsed.bozo_exception:
            logger.debug(
                "Bozo RSS feed for %s (%s): %s",
                tribunal,
                url,
                parsed.bozo_exception,
            )

        entries: list[dict[str, Any]] = parsed.get("entries", [])
        logger.debug("RSS %s: %d entries", tribunal, len(entries))
        return entries

    @staticmethod
    def _entry_to_fonte(tribunal: str, entry: dict[str, Any]) -> FonteJurisprudencia | None:
        """Convert a feedparser entry to FonteJurisprudencia.

        Args:
            tribunal: Court identifier.
            entry: feedparser entry dict.

        Returns:
            FonteJurisprudencia or None if the entry lacks a title.
        """
        title: str = entry.get("title", "").strip()
        if not title:
            return None

        url: str = entry.get("link", "")
        summary: str = entry.get("summary", entry.get("description", "")).strip()
        published_str: str = entry.get("published", "")

        data_julgamento = None
        if published_str:
            try:
                parsed_time = entry.get("published_parsed")
                if parsed_time:
                    data_julgamento = datetime(
                        parsed_time.tm_year,
                        parsed_time.tm_mon,
                        parsed_time.tm_mday,
                        parsed_time.tm_hour,
                        parsed_time.tm_min,
                        parsed_time.tm_sec,
                        tzinfo=UTC,
                    ).date()
            except (TypeError, ValueError):
                pass

        # Build a stable ID from tribunal + URL hash
        import hashlib
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        source_id = f"noticia_{tribunal.lower()}_{url_hash}"

        return FonteJurisprudencia(
            id=source_id,
            tribunal=tribunal,
            tipo=TipoFonte.NOTICIA_TRIBUNAL,
            numero=url_hash,
            ementa=title,
            texto_integral=summary or None,
            data_julgamento=data_julgamento,
            situacao="vigente",
            hierarquia=7,
            source_url=url or None,
            source_publisher=tribunal,
        )
