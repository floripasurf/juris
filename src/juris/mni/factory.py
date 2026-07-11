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
    from juris.api.agent_config import is_remote, tenant_agent_binding

    if is_remote():
        from juris.mni.remote import RelayAgentTransport, RemoteMNIReadService, WebSocketAgentTransport

        binding = tenant_agent_binding(tenant_id)  # routes to THIS firm's agent
        transport = (
            RelayAgentTransport(tenant_id)
            if binding.transport == "relay"
            else WebSocketAgentTransport(binding.base_url + "/ws/mni", token=binding.token)
        )
        return RemoteMNIReadService(transport, tenant_id=tenant_id)

    from juris.mni.service import InProcessMNIReadService

    return InProcessMNIReadService()
