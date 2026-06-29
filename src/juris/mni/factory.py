"""Factory that picks the MNI read service from config (ADR-0015).

``JURIS_AGENT_MODE=inprocess`` (default, CLI/pilot) reads in-process; ``remote``
forwards to the lawyer's local agent — swapping is config, not code.
"""

from __future__ import annotations

from juris.mni.service import MNIReadService


def get_mni_read_service(tenant_id: str = "public") -> MNIReadService:
    """Return the configured :class:`MNIReadService` (InProcess or Remote).

    ``tenant_id`` tags the remote requests for the agent's audit log.
    """
    from juris.api.agent_config import is_remote, local_agent_base_url, local_agent_token

    if is_remote():
        from juris.mni.remote import RemoteMNIReadService, WebSocketAgentTransport

        url = local_agent_base_url() + "/ws/mni"
        transport = WebSocketAgentTransport(url, token=local_agent_token())
        return RemoteMNIReadService(transport, tenant_id=tenant_id)

    from juris.mni.service import InProcessMNIReadService

    return InProcessMNIReadService()
