"""Factory that picks the signing service from config (ADR-0015).

``JURIS_AGENT_MODE=inprocess`` (default, CLI/pilot) signs in-process;
``remote`` forwards to the lawyer's local agent — swapping is config, not code.
"""

from __future__ import annotations

from juris.signing.service import SigningService


def get_signing_service(tenant_id: str = "public") -> SigningService:
    """Return the configured :class:`SigningService` (InProcess or Remote).

    ``tenant_id`` tags the remote requests for the agent's audit log.
    """
    from juris.api.agent_config import is_remote, local_agent_base_url, local_agent_token

    if is_remote():
        from juris.signing.remote import RemoteSigningService, WebSocketSignTransport

        url = local_agent_base_url() + "/ws/sign"
        transport = WebSocketSignTransport(url, token=local_agent_token())
        return RemoteSigningService(transport, tenant_id=tenant_id)

    from juris.signing.service import InProcessSigningService

    return InProcessSigningService()
