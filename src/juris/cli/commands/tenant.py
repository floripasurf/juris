"""``juris tenant`` — onboard a firm to the multi-tenant SaaS (hashed API keys)."""

from __future__ import annotations

import typer

from juris.cli.console import console

tenant_app = typer.Typer(name="tenant", help="Onboarding de escritório (multi-tenant).")


@tenant_app.command("hash-key")
def hash_key(
    api_key: str = typer.Argument(..., help="Chave em texto puro a ser hashada."),
) -> None:
    """Print the sha256 hash of an API key for JURIS_TENANTS_FILE.

    Store the HASH in the file; give the raw key to the firm (sent as X-API-Key).
    """
    from juris.web.auth import hash_api_key

    console.print(hash_api_key(api_key))


@tenant_app.command("new")
def new_tenant(
    tenant_id: str = typer.Argument(..., help="Identificador do escritório (a-z, 0-9, -, _)."),
) -> None:
    """Generate a fresh API key for a firm and print its JURIS_TENANTS_FILE entry.

    The RAW key is shown once — give it to the firm (X-API-Key) and never store it;
    only the hash goes into the config.
    """
    import secrets

    from juris.web.auth import _validate_tenant_id, hash_api_key

    try:
        tid = _validate_tenant_id(tenant_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

    raw = secrets.token_urlsafe(32)
    console.print("[bold]Chave crua[/bold] (entregue ao escritório — enviar em X-API-Key, NÃO armazenar):")
    console.print(f"  {raw}\n")
    console.print("[bold]Entrada no JURIS_TENANTS_FILE[/bold] (armazene só o hash):")
    console.print(f'  "{tid}": "{hash_api_key(raw)}"')
