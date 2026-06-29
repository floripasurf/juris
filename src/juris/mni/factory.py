"""Factory that picks the MNI read service from config (ADR-0015).

``JURIS_AGENT_MODE=inprocess`` (default, CLI/pilot) reads in-process; ``remote``
forwards to the lawyer's local agent — swapping is config, not code.
"""

from __future__ import annotations

from juris.mni.service import MNIReadService


def get_mni_read_service() -> MNIReadService:
    """Return the configured :class:`MNIReadService` (InProcess or Remote)."""
    from juris.api.agent_config import is_remote, local_agent_base_url, local_agent_token

    if is_remote():
        from juris.mni.remote import RemoteMNIReadService, WebSocketAgentTransport

        url = local_agent_base_url() + "/ws/mni"
        transport = WebSocketAgentTransport(url, token=local_agent_token())
        return RemoteMNIReadService(transport)

    from juris.mni.service import InProcessMNIReadService

    return InProcessMNIReadService()
