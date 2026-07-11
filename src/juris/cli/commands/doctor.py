"""``juris doctor`` — validate a production multi-tenant deployment before go-live."""

from __future__ import annotations

import typer

from juris.cli.console import console


def doctor(
    tenant: str | None = typer.Option(
        None, "--tenant", help="Também roda o health operacional deste tenant."
    ),
) -> None:
    """Check production config: tenants, hashed keys, agent bindings, storage, permissions.

    Exits non-zero if any blocking check fails — wire it into your deploy/CI so a
    misconfigured multi-tenant deployment never reaches production.
    """
    from juris.ops.production import all_blocking_ok, check_production_readiness

    checks = check_production_readiness()
    console.print("[bold]juris doctor — produção multi-tenant[/bold]\n")
    for c in checks:
        if c.ok:
            icon = "[green]✓[/green]"
        elif c.severity == "warn":
            icon = "[yellow]![/yellow]"
        else:
            icon = "[red]✗[/red]"
        console.print(f"  {icon} [bold]{c.name}[/bold]: {c.detail}")

    blocking_ok = all_blocking_ok(checks)
    warns = [c for c in checks if c.severity == "warn" and not c.ok]
    console.print("")
    if blocking_ok:
        tail = f" ({len(warns)} aviso(s))" if warns else ""
        console.print(f"[green]Pronto para produção.[/green]{tail}")
    else:
        failed = [c.name for c in checks if c.severity == "error" and not c.ok]
        console.print(f"[red]NÃO pronto[/red] — corrija: {', '.join(failed)}")

    if tenant is not None:
        _print_tenant_health(tenant)

    if not blocking_ok:
        raise typer.Exit(code=1)


def _print_tenant_health(tenant_id: str) -> None:
    """Render the per-tenant operational status (config/agent/token/corpus/filing)."""
    from juris.ops.tenant_health import tenant_operational_status
    from juris.web.auth import Tenant

    console.print(f"\n[bold]Health operacional — tenant {tenant_id}[/bold]\n")
    status = tenant_operational_status(Tenant(tenant_id))
    for name, item in status["components"].items():
        icon = "[green]✓[/green]" if item["ok"] else "[yellow]![/yellow]"
        console.print(f"  {icon} [bold]{name}[/bold]: {item['detail']}")
