"""Registry for procedural-defense institutes by branch/code.

Keeps the CPC/CPP/CLT catalogs wired into the analyzer instead of leaving them as
standalone reference data.
"""

from __future__ import annotations

from juris.defesas.clt_rules import CLT_DEFESAS
from juris.defesas.context import ProcessoContext
from juris.defesas.cpc_rules import CPC_DEFESAS
from juris.defesas.cpp_rules import CPP_DEFESAS
from juris.defesas.models import CodigoProcessual, InstitutoProcessual, TipoDefesa

_BY_CODE: dict[CodigoProcessual, tuple[InstitutoProcessual, ...]] = {
    CodigoProcessual.CPC: tuple(CPC_DEFESAS),
    CodigoProcessual.CPP: tuple(CPP_DEFESAS),
    CodigoProcessual.CLT: tuple(CLT_DEFESAS),
}


def codigo_for_context(context: ProcessoContext) -> CodigoProcessual:
    """Infer the procedural-code catalog for a case context."""
    ramo = (context.ramo_justica or "").strip().lower()
    tribunal = (context.tribunal or "").strip().lower()
    classe = (context.classe or "").strip().lower()
    assuntos = " ".join(context.assuntos).lower()
    text = f"{ramo} {tribunal} {classe} {assuntos}"

    if "trabalho" in text or tribunal.startswith("trt"):
        return CodigoProcessual.CLT
    if any(marker in text for marker in ("penal", "criminal", "crime", "cpp")):
        return CodigoProcessual.CPP
    return CodigoProcessual.CPC


def institutos_for_code(codigo: CodigoProcessual) -> tuple[InstitutoProcessual, ...]:
    """Return the immutable catalog for one procedural code."""
    return _BY_CODE.get(codigo, ())


def institutos_for_context(context: ProcessoContext) -> tuple[InstitutoProcessual, ...]:
    """Return the catalog that should be consulted for this case."""
    return institutos_for_code(codigo_for_context(context))


def institutos_by_tipo(
    tipo: TipoDefesa,
    *,
    codigo: CodigoProcessual | None = None,
) -> tuple[InstitutoProcessual, ...]:
    """Return catalog entries for a defense type, optionally limited to one code."""
    catalogs = (institutos_for_code(codigo),) if codigo is not None else tuple(_BY_CODE.values())
    return tuple(inst for catalog in catalogs for inst in catalog if inst.tipo == tipo)
