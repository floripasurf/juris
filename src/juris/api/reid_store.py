"""Agent-local store for de-identification maps (ADR-0015 / ADR-0016 split-trust).

When the agent de-identifies a processo before returning it to the (Phase-2 SaaS)
cloud, the re-identification map stays HERE — on the lawyer's machine, owner-only,
never on the wire. The final petition is re-identified locally from this map, so the
cloud only ever holds placeholder-bearing case data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from juris.core.paths import ensure_private_dir, juris_home, restrict_file
from juris.web.auth import validate_tenant_id

_CNJ_SAFE = re.compile(r"[^0-9.\-]")


def _reid_dir(tenant_id: str) -> Path:
    """Owner-only directory holding this tenant's re-id maps, under $JURIS_HOME."""
    return juris_home() / "agent" / "reid-maps" / validate_tenant_id(tenant_id)


def _map_filename(numero_cnj: str) -> str:
    """A traversal-safe filename derived from the CNJ (digits, dots, dashes only)."""
    cleaned = _CNJ_SAFE.sub("", numero_cnj)
    if not re.search(r"\d", cleaned):
        msg = "numero_cnj inválido para chave do mapa de re-id."
        raise ValueError(msg)
    return f"{cleaned}.json"


def save_reid_map(tenant_id: str, numero_cnj: str, mapping: dict[str, str]) -> Path:
    """Persist a re-id map locally (owner-only), keyed by tenant + CNJ."""
    directory = _reid_dir(tenant_id)
    ensure_private_dir(directory)
    path = directory / _map_filename(numero_cnj)
    path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    restrict_file(path)
    return path


def load_reid_map(tenant_id: str, numero_cnj: str) -> dict[str, str]:
    """Load the re-id map for a case, or an empty map if none was stored."""
    path = _reid_dir(tenant_id) / _map_filename(numero_cnj)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}
