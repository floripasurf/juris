#!/usr/bin/env python3
"""Generate the TST Súmulas corpus seed from the official Livro de Súmulas.

Source: the official TST book "Súmulas, Orientações Jurisprudenciais e
Precedentes Normativos" (RTF export, converted to text via macOS `textutil`).
The RTF text is clean — no column de-hyphenation, no running page headers —
unlike the PDF, so entries can be sliced deterministically.

Entry layout (one per súmula):

    SUM-<N>\t<TÍTULO> (...notas...) – Res. NNN/AAAA, DEJT...
    <corpo: texto consolidado vigente, possivelmente em itens I, II, ...>
    Histórico:
    <versões anteriores — EXCLUÍDAS do enunciado>

Rules (integrity-critical):
* Entry boundary = this ``SUM-<N>`` header to the next ``SUM-<N>`` header.
* The enunciado is the body up to ``Histórico:`` — the histórico holds
  superseded/old wording and must never enter the seed.
* ``situacao`` = cancelada ONLY when the official TITLE carries "(cancelada"
  — never inferred from the word "cancelada" appearing in body items.

Output: data/corpus/sumulas_tst.json
Schema per entry: {numero, texto, tema, base_legal[], situacao, data_aprovacao}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Text produced by: textutil -convert txt -encoding UTF-8 livrointernet12rtf.rtf
SRC = Path("/tmp/tst_rtf.txt")

# A primary súmula header: start-of-line "SUM-<N>" then a tab OR space and the
# title. Some headers are indented and a few use a space separator instead of a
# tab, so allow leading whitespace and either separator. The title must start
# with a non-space char (filters stray references).
_HEADER = re.compile(r"(?m)^[ \t]*SUM-(\d+)[\t ]+(\S.*)$")
_HIST = re.compile(r"\bHist[óo]rico:\s*", re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\xa0", " ")).strip()


def _tema_from_title(title_line: str) -> str:
    """The thematic caption is the title before the first parenthetical/resolution."""
    t = re.split(r"\s*[–-]\s*Res\.|\s*\(", title_line, maxsplit=1)[0]
    return _clean(t)


def _is_cancelada(title_line: str) -> bool:
    # Official cancellation marker lives in the title: "(cancelada" / "(cancelado".
    head = title_line[:300].lower()
    return bool(re.search(r"\(cancelad[ao]\b", head))


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    out_path = repo_root / "data" / "corpus" / "sumulas_tst.json"

    full = SRC.read_text(encoding="utf-8", errors="replace")
    # Restrict to the Súmulas region: everything before the OJ section.
    oj = re.search(r"\bOJ-[A-Z]", full)
    region = full[: oj.start()] if oj else full

    headers = list(_HEADER.finditer(region))
    print(f"{len(headers)} cabeçalhos SUM- na região de súmulas")

    # Keep only the FIRST (primary, definitional) occurrence of each número;
    # later repeats are cross-references inside other entries' histórico.
    records: dict[int, dict] = {}
    for idx, m in enumerate(headers):
        numero = int(m.group(1))
        if numero in records:
            continue
        title_line = m.group(2)
        body_start = m.end()
        body_end = headers[idx + 1].start() if idx + 1 < len(headers) else len(region)
        block = region[body_start:body_end]
        # Cut the histórico tail (superseded wording).
        hist = _HIST.search(block)
        if hist:
            block = block[: hist.start()]
        texto = _clean(block)
        situacao = "cancelada" if _is_cancelada(title_line) else "vigente"
        # For cancelled súmulas the body is typically empty/just the marker.
        if situacao == "cancelada" and len(texto) < 15:
            texto = _clean(title_line)
        records[numero] = {
            "numero": str(numero),
            "texto": texto,
            "tema": _tema_from_title(title_line),
            "base_legal": [],
            "situacao": situacao,
            "data_aprovacao": "",
        }

    ordered = [records[n] for n in sorted(records)]
    out_path.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    nums = sorted(records)
    missing = [n for n in range(1, max(nums) + 1) if n not in records]
    canc = [n for n in nums if records[n]["situacao"] == "cancelada"]
    print(f"súmulas distintas: {len(records)} | range {nums[0]}-{nums[-1]}")
    print(f"faltando no range: {missing}")
    print(f"canceladas: {len(canc)} | vigentes: {len(records) - len(canc)}")
    empty = [n for n in nums if not records[n]["texto"].strip()]
    print(f"texto vazio: {empty}")
    print(f"\nWrote {len(ordered)} entries -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
