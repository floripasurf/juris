"""De-identify a ProcessoDomain at the split-trust boundary (ADR-0015 + ADR-0016).

In Phase-2 SaaS mode the lawyer's local agent reads MNI, then returns the processo to
the cloud orchestrator (a third party under the split-trust model). Party names and CPFs
must not cross raw. This module rewrites the PII-bearing fields to reversible placeholders
using one shared map, so:

* the payload that crosses carries only ``[NOME_1]`` / ``[CPF_1]`` style tokens;
* the re-identification map stays LOCAL to the agent (the caller persists it), to be
  applied when the final petition is produced on the lawyer's side.

The party and lawyer names are taken from the processo itself, so redaction is
deterministic and complete for them — no statistical NER guess is needed.
"""

from __future__ import annotations

from dataclasses import replace

from juris.core.deid import Deidentifier
from juris.mni.parsers.processo import ProcessoDomain


def _known_entities(processo: ProcessoDomain) -> list[str]:
    """Every party/lawyer name AND document number the processo carries — the
    deterministic redaction set. Documents are included as KNOWN values because MNI
    returns them unformatted (bare digits), which the structured CPF/CNPJ regexes
    (dotted-only) would otherwise miss — so redacting the literal value is what stops a
    digits-only CPF/CNPJ from crossing raw.
    """
    entities: list[str] = []
    for parte in processo.partes:
        if parte.nome:
            entities.append(parte.nome)
        if parte.documento:
            entities.append(parte.documento)
        entities.extend(adv for adv in parte.advogados if adv)
    return entities


def deidentify_processo(processo: ProcessoDomain) -> tuple[ProcessoDomain, dict[str, str]]:
    """Return a de-identified copy of ``processo`` plus the local re-identification map.

    ``numero_cnj`` (the routing/correlation key, not a party identifier) is preserved;
    names, documents (CPF/CNPJ — formatted OR bare digits) and free-text movements are
    redacted to reversible placeholders sharing one map. Apply
    :func:`juris.core.deid.reidentify` with the returned map to restore the originals.
    """
    engine = Deidentifier()
    known = _known_entities(processo)

    def _txt(value: str | None) -> str | None:
        return engine.redact(value, known_entities=known) if value else value

    partes = [
        replace(
            parte,
            nome=engine.redact(parte.nome, known_entities=known) if parte.nome else parte.nome,
            documento=engine.redact(parte.documento, known_entities=known) if parte.documento else None,
            advogados=[engine.redact(adv, known_entities=known) for adv in parte.advogados],
        )
        for parte in processo.partes
    ]
    movimentos = [
        replace(mov, descricao=_txt(mov.descricao), complemento=_txt(mov.complemento))
        for mov in processo.movimentos
    ]

    deid = replace(processo, partes=partes, movimentos=movimentos)
    return deid, engine.mapping
