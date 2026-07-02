"""``juris tenant`` — onboard a firm to the multi-tenant SaaS (hashed API keys)."""

from __future__ import annotations

import typer
from rich.table import Table

from juris.cli.console import console
from juris.ops.erasure import TenantErasurePlan

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


@tenant_app.command("erase-data")
def erase_data(
    tenant_id: str = typer.Argument(..., help="Tenant/escritório cujos dados serão apagados."),
    execute: bool = typer.Option(False, "--execute", help="Executa a deleção. Sem isso, apenas mostra o plano."),
    confirm: str | None = typer.Option(
        None,
        "--confirm",
        help="Frase exata de confirmação mostrada no dry-run, ex.: ERASE-escritorio-a.",
    ),
    allow_public: bool = typer.Option(
        False,
        "--allow-public",
        help="Permite planejar/executar deleção do tenant legado `public`.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emite JSON para automação/runbook."),
) -> None:
    """Planeja ou executa a deleção LGPD de dados locais de um tenant."""
    import json

    from juris.ops.erasure import build_tenant_erasure_plan, execute_tenant_erasure

    try:
        plan = build_tenant_erasure_plan(tenant_id, allow_public=allow_public)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    if not execute:
        if json_output:
            console.print_json(json.dumps({"dry_run": True, "plan": plan.to_dict()}, ensure_ascii=False))
        else:
            _print_erasure_plan(plan)
        return

    try:
        result = execute_tenant_erasure(plan, confirmation=confirm or "")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    if json_output:
        console.print_json(json.dumps({"dry_run": False, "result": result.to_dict()}, ensure_ascii=False))
        return
    console.print(f"[green]Dados apagados para tenant:[/green] {result.tenant_id}")
    console.print(f"  Alvos removidos: {result.targets_deleted}")
    console.print(f"  Arquivos: {result.files_deleted} ({result.bytes_deleted} bytes)")
    console.print(f"  Connect jobs: {result.connect_jobs_deleted}")
    console.print(f"  Chunks privados do corpus: {result.corpus_chunks_deleted}")
    console.print(f"  Certificado: {result.erasure_log_path}")
    for warning in result.warnings:
        console.print(f"[yellow]Aviso:[/yellow] {warning}")


def _print_erasure_plan(plan: TenantErasurePlan) -> None:
    console.print(f"[bold]Plano de deleção LGPD:[/bold] {plan.tenant_id}")
    console.print(f"  Arquivos: {plan.file_count} ({plan.total_bytes} bytes)")
    console.print(f"  Connect jobs: {plan.connect_jobs}")
    console.print(f"  Chunks privados do corpus: {plan.corpus_chunks}")
    console.print(f"  Certificado será registrado em: {plan.erasure_log_path}")
    table = Table(title="Alvos de filesystem")
    table.add_column("Tipo")
    table.add_column("Existe")
    table.add_column("Arquivos", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("Path", overflow="fold")
    for target in plan.targets:
        table.add_row(
            target.kind,
            "sim" if target.exists else "não",
            str(target.file_count),
            str(target.total_bytes),
            str(target.path),
        )
    console.print(table)
    for warning in plan.warnings:
        console.print(f"[yellow]Aviso:[/yellow] {warning}")
    console.print(f"[yellow]Dry-run apenas.[/yellow] Para executar: --execute --confirm {plan.confirmation_phrase}")
