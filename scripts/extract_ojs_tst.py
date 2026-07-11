#!/usr/bin/env python3
"""Generate the TST Orientações Jurisprudenciais (OJs) corpus seed.

Same official source and parsing rules as ``extract_sumulas_tst.py``. OJ
entries live between the Súmulas and the Precedentes Normativos sections and
are keyed by section + number (e.g. ``SDI1-191``), since numbers repeat across
SBDI-I, SBDI-I Transitória, SBDI-II, SDC and Tribunal Pleno/Órgão Especial.

Entry layout:

    OJ-<SEÇÃO>-<N>\t<TÍTULO> (...notas...) - DJ/DEJT...
    <corpo vigente>
    Histórico:
    <versões anteriores — EXCLUÍDAS>

``situacao`` = cancelada ONLY from the official "(cancelad" title marker.

Output: data/corpus/ojs_tst.json
Schema per entry: {numero, texto, tema, base_legal[], situacao, data_aprovacao}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

M = re.MULTILINE
SRC = Path("/tmp/tst_rtf.txt")

# OJ header: "OJ-<SECTION>-<NUM>" then tab/space and title. SECTION is one of
# SDC, SDI1, SDI1T, SDI2, TP/OE. NUM may carry a trailing letter.
_HEADER = re.compile(r"^[ \t]*OJ-([A-Za-z0-9/]+)-(\d+[A-Z]?)[\t ]+(\S.*)$", M)
_HIST = re.compile(r"\bHist[óo]rico:\s*", re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\xa0", " ")).strip()


def _tema(title_line: str) -> str:
    t = re.split(r"\s*[–-]\s*(?:DJ|DEJT|Res\.)|\s*\(", title_line, maxsplit=1)[0]
    return _clean(t)


def _is_cancelada(title_line: str) -> bool:
    return bool(re.search(r"\(cancelad[ao]\b", title_line[:300].lower()))


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    out_path = repo_root / "data" / "corpus" / "ojs_tst.json"

    full = SRC.read_text(encoding="utf-8", errors="replace")
    oj0 = re.search(r"^[ \t]*OJ-[A-Z]", full, M)
    pn = re.search(r"^[ \t]*PN-\d+[\t ]", full, M)
    region = full[oj0.start():(pn.start() if pn else len(full))]

    headers = list(_HEADER.finditer(region))
    print(f"{len(headers)} cabeçalhos OJ na região")

    records: dict[str, dict] = {}
    for idx, m in enumerate(headers):
        section, num, title_line = m.group(1), m.group(2), m.group(3)
        key = f"{section}-{num}"
        if key in records:
            continue
        body_start = m.end()
        body_end = headers[idx + 1].start() if idx + 1 < len(headers) else len(region)
        block = region[body_start:body_end]
        hist = _HIST.search(block)
        if hist:
            block = block[: hist.start()]
        texto = _clean(block)
        situacao = "cancelada" if _is_cancelada(title_line) else "vigente"
        if situacao == "cancelada" and len(texto) < 15:
            texto = _clean(title_line)
        records[key] = {
            "numero": key,
            "texto": texto,
            "tema": _tema(title_line),
            "base_legal": [],
            "situacao": situacao,
            "data_aprovacao": "",
        }

    def _sort_key(k: str) -> tuple[str, int, str]:
        sec, _, n = k.rpartition("-")
        digits = re.match(r"\d+", n)
        return (sec, int(digits.group()) if digits else 0, n)

    ordered = [records[k] for k in sorted(records, key=_sort_key)]
    out_path.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    by_sec: dict[str, int] = {}
    canc = 0
    for r in ordered:
        sec = r["numero"].rpartition("-")[0]
        by_sec[sec] = by_sec.get(sec, 0) + 1
        if r["situacao"] == "cancelada":
            canc += 1
    print(f"OJs distintas: {len(records)} | por seção: {by_sec}")
    print(f"canceladas: {canc} | vigentes: {len(records) - canc}")
    empty = [r["numero"] for r in ordered if not r["texto"].strip()]
    print(f"texto vazio: {empty}")
    print(f"\nWrote {len(ordered)} entries -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
