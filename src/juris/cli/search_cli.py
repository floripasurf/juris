"""CLI subcommand for unified multi-court jurisprudence search."""
from __future__ import annotations

import asyncio
import json as json_module

import typer
from rich.console import Console
from rich.table import Table

from juris.search.cnj_router import cnj_to_court
from juris.search.dispatcher import SearchDispatcher
from juris.search.models import SearchQuery

search_app = typer.Typer(
    name="search",
    help="Search jurisprudence across multiple courts in parallel.",
    no_args_is_help=True,
)
console = Console()


def _resolve_query(
    tema: str | None,
    oab: str | None,
    nome: str | None,
    cpf: str | None,
    cnpj: str | None,
    cnj: str | None,
) -> tuple[str, str]:
    """Return (query_type, value) from mutually exclusive options."""
    options = [
        ("tema", tema),
        ("oab", oab),
        ("nome", nome),
        ("cpf", cpf),
        ("cnpj", cnpj),
        ("cnj", cnj),
    ]
    provided = [(qt, v) for qt, v in options if v is not None]
    if len(provided) == 0:
        console.print("[red]Error:[/red] Provide at least one query type (--tema, --oab, --nome, --cpf, --cnpj, --cnj)")
        raise typer.Exit(code=1)
    if len(provided) > 1:
        console.print("[red]Error:[/red] Only one query type at a time")
        raise typer.Exit(code=1)
    return provided[0]


@search_app.callback(invoke_without_command=True)
def search_command(
    ctx: typer.Context,
    tema: str | None = typer.Option(None, "--tema", "-t", help="Search by topic/theme"),
    oab: str | None = typer.Option(None, "--oab", help="Search by OAB number"),
    nome: str | None = typer.Option(None, "--nome", "-n", help="Search by name"),
    cpf: str | None = typer.Option(None, "--cpf", help="Search by CPF"),
    cnpj: str | None = typer.Option(None, "--cnpj", help="Search by CNPJ"),
    cnj: str | None = typer.Option(None, "--cnj", help="Search by CNJ number"),
    courts: str = typer.Option("stf,stj", "--courts", "-c", help="Comma-separated court codes, or 'all'"),
    date_from: str | None = typer.Option(None, "--from", help="Start date (dd/mm/yyyy)"),
    date_to: str | None = typer.Option(None, "--to", help="End date (dd/mm/yyyy)"),
    max_per_court: int = typer.Option(20, "--max", help="Max results per court"),
    output_format: str = typer.Option("table", "--format", "-f", help="Output format: table, json, markdown"),
    explain: bool = typer.Option(False, "--explain", help="Show debug/explain info"),
) -> None:
    """Search jurisprudence across multiple courts in parallel."""
    if ctx.invoked_subcommand is not None:
        return

    # Check all None = no query
    if all(x is None for x in [tema, oab, nome, cpf, cnpj, cnj]):
        console.print("[red]Error:[/red] Provide at least one query type")
        raise typer.Exit(code=1)

    query_type, value = _resolve_query(tema, oab, nome, cpf, cnpj, cnj)

    # Parse date range
    date_range = None
    if date_from or date_to:
        from juris.search.utils import parse_br_date
        d_from = parse_br_date(date_from) if date_from else None
        d_to = parse_br_date(date_to) if date_to else None
        if d_from and d_to:
            date_range = (d_from, d_to)

    query = SearchQuery(
        query_type=query_type,
        value=value,
        date_range=date_range,
        max_results_per_court=max_per_court,
    )

    # Resolve courts
    court_list: list[str] | None = None
    if query_type == "cnj":
        # Auto-route by CNJ number
        detected = cnj_to_court(value)
        if detected:
            court_list = [detected]
            console.print(f"[dim]CNJ auto-routed to: {detected}[/dim]")
        else:
            console.print("[yellow]Warning:[/yellow] Could not auto-detect court from CNJ, searching all")
    elif courts != "all":
        court_list = [c.strip() for c in courts.split(",") if c.strip()]

    dispatcher = SearchDispatcher()
    response = asyncio.run(dispatcher.search(query, courts=court_list, explain=explain))

    if output_format == "json":
        _print_json(response)
    elif output_format == "markdown":
        _print_markdown(response)
    else:
        _print_table(response)

    if explain and response.explain:
        _print_explain(response.explain)

    if response.courts_failed:
        for court, error in response.courts_failed:
            console.print(f"[yellow]Warning:[/yellow] {court}: {error}")


def _print_table(response: object) -> None:
    """Print results as a rich table."""
    table = Table(title=f"Search Results ({response.total_count} found, {response.elapsed_seconds:.1f}s)")
    table.add_column("Court", style="cyan", width=6)
    table.add_column("Case", width=30)
    table.add_column("Date", width=12)
    table.add_column("Relator", width=25)
    table.add_column("Ementa", width=60)

    for r in response.results:
        date_str = r.decision_date.strftime("%d/%m/%Y") if r.decision_date else "-"
        ementa_short = r.ementa[:57] + "..." if len(r.ementa) > 60 else r.ementa
        table.add_row(
            r.court.upper(),
            r.case_number,
            date_str,
            r.relator or "-",
            ementa_short,
        )
    console.print(table)


def _print_json(response: object) -> None:
    """Print results as JSON."""
    data = {
        "query": {"type": response.query.query_type, "value": response.query.value},
        "total": response.total_count,
        "elapsed_seconds": response.elapsed_seconds,
        "results": [
            {
                "court": r.court,
                "case_number": r.case_number,
                "cnj_number": r.cnj_number,
                "decision_date": r.decision_date.isoformat() if r.decision_date else None,
                "relator": r.relator,
                "classe": r.classe,
                "ementa": r.ementa,
                "url": r.url,
            }
            for r in response.results
        ],
    }
    console.print_json(json_module.dumps(data, ensure_ascii=False, indent=2))


def _print_markdown(response: object) -> None:
    """Print results as markdown."""
    for i, r in enumerate(response.results, 1):
        date_str = r.decision_date.strftime("%d/%m/%Y") if r.decision_date else "N/A"
        console.print(f"### {i}. [{r.court.upper()}] {r.case_number}")
        console.print(f"**Relator:** {r.relator or 'N/A'} | **Data:** {date_str}")
        console.print(f"\n{r.ementa}\n")
        console.print(f"[link={r.url}]{r.url}[/link]\n")
        console.print("---\n")


def _print_explain(explain: object) -> None:
    """Print explain/debug information."""
    console.print("\n[bold]--- Explain ---[/bold]")
    console.print(f"Courts requested: {explain.courts_requested}")
    if explain.courts_skipped:
        console.print(f"Courts skipped: {explain.courts_skipped}")
    console.print(f"Per-court latency: {explain.per_court_latency}")
    console.print(f"Ranking weights: {explain.ranking_weights}")
    console.print(f"Dedup removed: {explain.dedup_removed}")


@search_app.command()
def doctor() -> None:
    """Run health checks against all registered court portal adapters."""
    from juris.search.adapters import get_all_adapters
    from juris.search.adapters.base import SearchAdapter

    adapter_classes = get_all_adapters()
    if not adapter_classes:
        console.print("[red]No adapters found[/red]")
        raise typer.Exit(code=1)

    adapters: list[SearchAdapter] = [cls() for cls in adapter_classes.values()]

    async def _run_checks() -> list:
        tasks = [a.health_check() for a in adapters]
        return await asyncio.gather(*tasks)

    results = asyncio.run(_run_checks())

    table = Table(title="Search Adapter Health Checks")
    table.add_column("Court", style="cyan")
    table.add_column("Status")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Error")

    any_unhealthy = False
    for hc in sorted(results, key=lambda h: h.court):
        status = "[green]OK[/green]" if hc.healthy else "[red]FAIL[/red]"
        if not hc.healthy:
            any_unhealthy = True
        table.add_row(
            hc.court.upper(),
            status,
            f"{hc.latency_ms:.0f}",
            hc.error or "",
        )

    console.print(table)
    if any_unhealthy:
        raise typer.Exit(code=1)
