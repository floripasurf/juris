"""Live filing integration test — requires real A3 token + MNI endpoint.

Run with: uv run pytest tests/integration/test_filing_live.py -m live
"""

from __future__ import annotations

import pytest


@pytest.mark.live
def test_real_filing_tjmg() -> None:
    """File a real petition to TJMG via MNI.

    Requires:
    - ICP-Brasil A3 token connected
    - Valid CPF/senha for TJMG
    - Active caso number

    This test is NOT run in CI.
    """
    pytest.skip("Live filing test — run manually with real credentials")
