"""Legal basis classifications for corpus provenance tracking."""

from __future__ import annotations

from enum import StrEnum


class LegalBasis(StrEnum):
    """Classification of the legal basis for including a source in the corpus."""

    PUBLIC_DOMAIN = "public_domain"
    OPEN_LICENSE = "open_license"
    GOVERNMENT_PUBLICATION = "government_publication"
    RESEARCH_PORTAL = "research_portal"
    INSTITUTIONAL_TEMPLATE = "institutional_template"
