#!/usr/bin/env python3
"""Generate the STF Súmulas Vinculantes corpus seed as JSON.

Texts are fetched verbatim from the official STF portal
(https://portal.stf.jus.br/jurisprudencia/sumariosumulas.asp?base=26) — the
enunciado is the first ``parCOM`` block following each SV title, captured
exactly as published (no paraphrase). The portal uses a self-signed cert, so
TLS verification is disabled (same approach as the original Sprint 13 scraper).

Output: data/corpus/sumulas_vinculantes.json
Schema per entry: {numero, texto, tema, base_legal[], situacao, data_aprovacao}
"""

from __future__ import annotations

import html as htmllib
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://portal.stf.jus.br/jurisprudencia/sumariosumulas.asp?base=26"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": BASE,
}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _fetch(url: str, attempts: int = 4) -> str:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)  # noqa: S310
            with urllib.request.urlopen(req, context=_CTX, timeout=45) as resp:  # noqa: S310
                return resp.read().decode("utf-8", errors="replace")
        except (TimeoutError, urllib.error.URLError, OSError) as exc:  # transient
            last = exc
            time.sleep(2.0)
    raise RuntimeError(f"fetch falhou após {attempts} tentativas: {url}") from last


def _clean(fragment: str) -> str:
    """Strip inner tags, unescape entities, collapse whitespace — verbatim text."""
    text = re.sub(r"<[^>]+>", "", fragment)
    text = htmllib.unescape(text).replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def _parse_list(summary_html: str) -> list[tuple[int, str, str]]:
    """Return (numero, sumula_id, situacao) for every SV in the summary page."""
    start = summary_html.find("Súmulas Vinculantes")
    section = summary_html[start:]
    pattern = re.compile(
        r"sumula=(\d+)[^>]*>\s*S[úu]mula Vinculante[\s\xa0&nbsp;]*?(\d+)\s*(<em>.*?</em>)?",
        re.IGNORECASE,
    )
    out: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for sid, num, marker in pattern.findall(section):
        if num in seen:
            continue
        seen.add(num)
        situacao = "vigente"
        if marker and re.search(r"cance|revog|super", _clean(marker), re.IGNORECASE):
            situacao = "cancelada"
        out.append((int(num), sid, situacao))
    out.sort()
    return out


def _parse_enunciado(detail_html: str, numero: int) -> str:
    """Extract the verbatim enunciado.

    The enunciado lives between the SV title block and the next ``titulo``
    block (``Precedente(s) Representativo(s)``). Slicing on that boundary is
    robust to multi-paragraph enunciados with nested ``<div>`` elements —
    capturing only the parCOM would either truncate or, when greedy, leak the
    precedents section into the text.
    """
    anchor = re.search(
        rf'class="titulo">\s*S[úu]mula Vinculante[\s\xa0&nbsp;]*{numero}\b',
        detail_html,
    )
    if not anchor:
        raise ValueError(f"título da SV {numero} não encontrado")
    rest = detail_html[anchor.end():]
    # Close the SV-title div, then take everything up to the next titulo div.
    body = rest.split("</div>", 1)[1] if "</div>" in rest else rest
    nxt = re.search(r'<div class="titulo"', body)
    enunciado_html = body[: nxt.start()] if nxt else body
    return _clean(enunciado_html)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    out_path = repo_root / "data" / "corpus" / "sumulas_vinculantes.json"

    print(f"Fetching summary: {BASE}")
    items = _parse_list(_fetch(BASE))
    print(f"  {len(items)} SV listadas (canceladas: "
          f"{[n for n, _, s in items if s != 'vigente']})")

    records: list[dict] = []
    for numero, sid, situacao in items:
        detail = _fetch(f"{BASE}&sumula={sid}")
        texto = _parse_enunciado(detail, numero)
        if not texto:
            print(f"  ! SV {numero}: enunciado vazio", file=sys.stderr)
            continue
        # situacao comes ONLY from the official summary-page marker (parsed in
        # _parse_list). Never infer it from words like "revogada"/"cancelada"
        # inside the enunciado — those refer to cited laws, not the SV's status.
        records.append({
            "numero": str(numero),
            "texto": texto,
            "tema": "",
            "base_legal": [],
            "situacao": situacao,
            "data_aprovacao": "",
        })
        print(f"  SV {numero:>2} [{situacao}]: {texto[:70]}...")

    out_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {len(records)} entries -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
