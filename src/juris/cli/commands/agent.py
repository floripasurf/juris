"""``juris agent`` — local-agent pairing, health, serve, and reverse-channel (ADR-0015).

Extracted from the monolithic ``cli/main.py`` (the split-plan target is one command
group per module, each < 400 lines).
"""

from __future__ import annotations

import typer

from juris.cli.console import console

agent_app = typer.Typer(name="agent", help="Local agent pairing + readiness (ADR-0015).")


@agent_app.command("pair")
def agent_pair() -> None:
    """Mint a pairing token and show how to configure both sides (split-trust)."""
    from juris.api.pairing import generate_pairing_token

    token = generate_pairing_token()
    console.print("[bold]Token de pareamento gerado[/bold] — use o MESMO valor nos dois lados:\n")
    console.print(f"  No AGENTE (máquina do advogado):   export JURIS_AGENT_TOKEN={token}")
    console.print(f"  No ORQUESTRADOR (nuvem):           export JURIS_LOCAL_AGENT_TOKEN={token}\n")
    console.print(
        "  No orquestrador, ative o modo remoto:\n"
        "    export JURIS_AGENT_MODE=remote\n"
        "    export JURIS_LOCAL_AGENT_URL=ws://<host-do-agente>:<porta>\n"
    )
    console.print("Valide com: [cyan]juris agent health --url ws://<host>:<porta>[/cyan]")


@agent_app.command("health")
def agent_health_cmd(
    url: str = typer.Option("ws://127.0.0.1:8765", "--url", help="URL base do agente (ws:// ou http://)."),
) -> None:
    """Probe the local agent's /health — reachability + token readiness."""
    from juris.api.pairing import check_agent_health

    try:
        health = check_agent_health(url)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    token_state = "[green]conectado[/green]" if health.token_connected else "[yellow]ausente[/yellow]"
    console.print(
        f"Agente v{health.version} — token: {token_state}; "
        f"cert válido até: {health.cert_valid_until or '—'}"
    )


@agent_app.command("serve")
def agent_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host — apenas loopback."),
    port: int = typer.Option(8765, "--port", help="Porta do agente."),
) -> None:
    """Run the lawyer-side local agent (the token holder) — loopback-only.

    The agent must never be reachable off the machine: ``--host`` is validated to
    127.0.0.1. Set ``JURIS_AGENT_TOKEN`` (pairing), ``JURIS_AGENT_CPF/SENHA/PIN``
    (the lawyer's secrets, resolved here) before serving.
    """
    import os

    from juris.api.local_agent import app as agent_asgi
    from juris.api.local_agent import get_signing_token, validate_local_agent_host

    try:
        bind_host = validate_local_agent_host(host)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

    # Fail closed: a token-holding boundary must not start with an unknown random token.
    if not os.environ.get("JURIS_AGENT_TOKEN"):
        console.print(
            "[red]JURIS_AGENT_TOKEN não definido.[/red] Rode 'juris agent pair' e exporte "
            "o token antes de servir (sem isso, ninguém consegue autenticar)."
        )
        raise typer.Exit(code=2)

    token = get_signing_token()
    masked = f"{token[:4]}…{token[-2:]}" if len(token) > 8 else "configurado"
    console.print(f"[bold]Agente local[/bold] em ws://{bind_host}:{port} (somente loopback)")
    # Never echo the full token in the long-running process (its stdout may go to a
    # log file). The full value is shown only by `juris agent pair`.
    console.print(f"Token de pareamento: {masked} (use 'juris agent pair' para o valor completo)")
    console.print("Ctrl-C para sair.")

    import uvicorn

    # Keep access logs off: request lines are unnecessary for this token-holding process,
    # and legacy deployments may temporarily re-enable ?token= during migration.
    uvicorn.run(agent_asgi, host=bind_host, port=port, log_level="warning", access_log=False)


@agent_app.command("connect-relay")
def agent_connect_relay(
    url: str = typer.Argument(..., help="URL do relay do orquestrador, ex.: wss://juris.cloud/ws/agent-relay"),
    tenant: str = typer.Option("public", "--tenant", help="Tenant deste agente."),
) -> None:
    """Dial OUT to the orchestrator's reverse channel and serve token ops over it.

    For non-co-located deploys: the agent (behind NAT) connects to the cloud instead of
    the cloud reaching the agent. Requires ``JURIS_AGENT_TOKEN`` (+ CPF/SENHA/PIN).
    Use ``wss://`` so the channel is TLS-encrypted (mTLS if the relay requires a client
    cert). Reconnects are the operator's concern (run under a supervisor).
    """
    import os

    from juris.api.local_agent import run_relay_agent

    token = os.environ.get("JURIS_AGENT_TOKEN")
    if not token:
        console.print("[red]JURIS_AGENT_TOKEN não definido.[/red] Rode 'juris agent pair' primeiro.")
        raise typer.Exit(code=2)
    console.print(f"[bold]Agente[/bold] discando o relay {url} (tenant={tenant})… Ctrl-C para sair.")
    try:
        run_relay_agent(url, token, tenant)
    except KeyboardInterrupt:
        console.print("Encerrado.")
