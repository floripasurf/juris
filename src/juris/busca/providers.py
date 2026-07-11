"""Provider profiles — declared trust/posture per acquisition source (ADR-0017).

The Source Mesh resolves a capability (party search, processo, jurisprudence,
intimação) across redundant providers. Each provider declares a profile so trust
and legal posture are *registry data* instead of magic numbers scattered through
the orchestrator. This first slice covers the ``busca`` (party-search) channels;
the same shape extends to the other capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass

from juris.busca.models import FonteOrigem


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Declared properties of one acquisition provider.

    Attributes:
        fonte: Source identifier.
        trust: Base reliability for this capability (0–1) — also the base
            corroboration confidence when this source returns a result.
        merge_priority: Tie-breaker when the same datum comes from several
            sources (higher wins the field merge).
        fonte_publica: Reachable without restricted credentials.
        atras_captcha: Acquisition is gated by a captcha.
    """

    fonte: FonteOrigem
    trust: float
    merge_priority: int
    fonte_publica: bool = True
    atras_captcha: bool = False

    @property
    def base_confidence(self) -> float:
        """Base corroboration score contributed when this source returns a hit."""
        return self.trust

    @property
    def reliable(self) -> bool:
        """Whether this source is trusted enough to anchor a result on its own."""
        return self.trust >= 0.5


# Party-search providers. Trust mirrors the prior _RELIABLE_SOURCES (0.5) vs
# DataJud best-effort (0.3); merge_priority mirrors the prior _SOURCE_PRIORITY.
PROVIDER_PROFILES: dict[FonteOrigem, ProviderProfile] = {
    FonteOrigem.ESAJ: ProviderProfile(FonteOrigem.ESAJ, trust=0.5, merge_priority=5, atras_captcha=True),
    FonteOrigem.EPROC: ProviderProfile(FonteOrigem.EPROC, trust=0.5, merge_priority=4, atras_captcha=True),
    FonteOrigem.EJEF: ProviderProfile(FonteOrigem.EJEF, trust=0.5, merge_priority=3),
    FonteOrigem.PROJUDI: ProviderProfile(FonteOrigem.PROJUDI, trust=0.5, merge_priority=2, atras_captcha=True),
    FonteOrigem.DATAJUD: ProviderProfile(FonteOrigem.DATAJUD, trust=0.3, merge_priority=1),
}

_DEFAULT_PROFILE = ProviderProfile(FonteOrigem.DATAJUD, trust=0.3, merge_priority=0)


def get_profile(fonte: FonteOrigem) -> ProviderProfile:
    """Return the profile for a source, or a conservative default if unknown."""
    return PROVIDER_PROFILES.get(fonte, _DEFAULT_PROFILE)
