"""juris CLI — main entry point."""

from __future__ import annotations

import getpass

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="juris",
    help="Brazilian Legal AI for law firms — MNI integration, prazo engine, petition drafting.",
    no_args_is_help=True,
)
console = Console()


def _get_senha(tribunal: str, cpf: str, senha: str | None) -> str:
    """Get password: from arg, from stored credentials, or prompt once and store."""
    if senha:
        return senha

    from juris.core.credentials import get_credential, store_credential

    cred_key = f"mni_{tribunal}_{cpf}"
    stored = get_credential(cred_key)
    if stored:
        return stored

    # Prompt user for password and store it
    prompted = getpass.getpass(f"Senha PJe ({tribunal.upper()}) para CPF {cpf}: ")
    if prompted:
        store_credential(cred_key, prompted)
        console.print("[dim]Senha salva no Keychain. Não será solicitada novamente.[/dim]")
    return prompted or cpf


@app.command()
def consulta(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format (NNNNNNN-DD.AAAA.J.TR.OOOO)"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID (e.g., trt2, trf3, tjmg)"),
    com_documentos: bool = typer.Option(False, "--com-documentos", "-d", help="Include full documents"),
    cpf: str = typer.Option(..., "--cpf", help="CPF do consultante"),
    senha: str = typer.Option(None, "--senha", "-s", help="Senha PJe (prompted + saved if omitted)"),
) -> None:
    """Fetch a case from a tribunal via MNI consultarProcesso."""
    from juris.core.types import NumeroCNJ
    from juris.mni.auth import PasswordAuth
    from juris.mni.client import get_mni_client
    from juris.mni.operations.consulta import consultar_processo
    from juris.mni.parsers.processo import parse_processo

    try:
        cnj = NumeroCNJ(numero_cnj)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from e

    resolved_senha = _get_senha(tribunal, cpf, senha)
    auth = PasswordAuth(cpf=cpf, senha=resolved_senha)

    console.print(f"[bold]Fetching case:[/bold] {cnj}")
    console.print(f"  Tribunal: {tribunal}")

    try:
        client = get_mni_client(tribunal, auth)
        response = consultar_processo(
            client=client,
            id_consultante=auth.get_id_consultante(),
            senha_consultante=auth.get_senha_consultante(),
            numero_cnj=str(cnj),
            com_documentos=com_documentos,
        )
    except KeyError as e:
        console.print(f"[red]Tribunal not found:[/red] {e}")
        raise typer.Exit(code=1) from e
    except Exception as e:
        console.print(f"[red]MNI Error:[/red] {type(e).__name__}: {e}")
        raise typer.Exit(code=1) from e

    # Check MNI-level success
    sucesso = getattr(response, "sucesso", None)
    if sucesso is False:
        mensagem = getattr(response, "mensagem", "Unknown error")
        console.print(f"[red]MNI returned error:[/red] {mensagem}")

        # If auth failed, clear stored credential so user can re-enter
        if "login" in str(mensagem).lower() or "autenticação" in str(mensagem).lower():
            from juris.core.credentials import delete_credential

            delete_credential(f"mni_{tribunal}_{cpf}")
            console.print("[yellow]Stored credential cleared. Re-run to enter new password.[/yellow]")
        raise typer.Exit(code=1)

    processo = parse_processo(response, tribunal_id=tribunal)
    _print_processo(processo)


@app.command()
def login(
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
    cpf: str = typer.Option(..., "--cpf", help="CPF do consultante"),
) -> None:
    """Store PJe credentials for a tribunal (saved in macOS Keychain)."""
    from juris.core.credentials import store_credential

    senha = getpass.getpass(f"Senha PJe ({tribunal.upper()}) para CPF {cpf}: ")
    if not senha:
        console.print("[red]Senha cannot be empty.[/red]")
        raise typer.Exit(code=1)

    store_credential(f"mni_{tribunal}_{cpf}", senha)
    console.print(f"[green]Credentials saved for {tribunal.upper()}.[/green]")


@app.command()
def logout(
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
    cpf: str = typer.Option(..., "--cpf", help="CPF do consultante"),
) -> None:
    """Remove stored PJe credentials for a tribunal."""
    from juris.core.credentials import delete_credential

    delete_credential(f"mni_{tribunal}_{cpf}")
    console.print(f"[green]Credentials removed for {tribunal.upper()}.[/green]")


def _print_processo(processo) -> None:
    """Pretty-print a ProcessoDomain to the console."""
    console.print(f"\n[bold green]Processo: {processo.numero_cnj}[/bold green]")
    console.print(f"  Classe: {processo.classe or 'N/A'}")
    console.print(f"  Assunto: {processo.assunto or 'N/A'}")
    console.print(f"  Valor: R$ {processo.valor_causa:,.2f}" if processo.valor_causa else "  Valor: N/A")
    console.print(f"  Órgão: {processo.orgao_julgador or 'N/A'}")

    if processo.partes:
        console.print("\n[bold]Partes:[/bold]")
        for p in processo.partes:
            advs = f" (Advs: {', '.join(p.advogados)})" if p.advogados else ""
            console.print(f"  [{p.tipo}] {p.nome}{advs}")

    if processo.movimentos:
        console.print(f"\n[bold]Movimentos ({len(processo.movimentos)}):[/bold]")
        table = Table()
        table.add_column("Data", style="cyan", width=20)
        table.add_column("Código", width=8)
        table.add_column("Descrição")
        table.add_column("Complemento")

        for m in processo.movimentos[-10:]:  # Last 10
            table.add_row(
                m.data_hora.strftime("%Y-%m-%d %H:%M"),
                str(m.codigo_nacional or ""),
                m.descricao or "",
                (m.complemento or "")[:60],
            )
        console.print(table)

    if processo.documentos:
        console.print(f"\n[bold]Documentos ({len(processo.documentos)}):[/bold]")
        for d in processo.documentos:
            console.print(f"  [{d.id_documento}] {d.tipo_documento}: {d.descricao or ''}")


@app.command()
def datajud(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
) -> None:
    """Fetch a case from DataJud (CNJ public API). Works for all tribunals."""
    from juris.datajud.client import consultar_processo
    from juris.datajud.parser import parse_datajud_processo

    console.print(f"[bold]Fetching from DataJud:[/bold] {numero_cnj} ({tribunal})")

    try:
        source = consultar_processo(numero_cnj, tribunal)
    except Exception as e:
        console.print(f"[red]DataJud Error:[/red] {type(e).__name__}: {e}")
        raise typer.Exit(code=1) from e

    if source is None:
        console.print("[yellow]Case not found in DataJud.[/yellow]")
        raise typer.Exit(code=1)

    processo = parse_datajud_processo(source)
    _print_processo(processo)


@app.command()
def consulta_cert(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
    cpf: str = typer.Option(..., "--cpf", help="CPF do consultante"),
    com_documentos: bool = typer.Option(False, "--com-documentos", "-d", help="Include full documents"),
    pin: str = typer.Option(None, "--pin", help="Token PIN (prompted + saved if omitted)"),
) -> None:
    """Fetch a case using ICP-Brasil A3 token (mTLS via PKCS#11)."""
    from juris.core.credentials import get_credential, store_credential
    from juris.core.types import NumeroCNJ
    from juris.mni.operations.consulta_pkcs11 import consultar_processo_pkcs11
    from juris.mni.pkcs11_transport import PKCS11Config
    from juris.mni.tribunais import get_tribunal

    try:
        cnj = NumeroCNJ(numero_cnj)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from e

    try:
        tribunal_cfg = get_tribunal(tribunal)
    except KeyError as e:
        console.print(f"[red]Tribunal not found:[/red] {e}")
        raise typer.Exit(code=1) from e

    # Resolve PIN: arg > stored > prompt
    resolved_pin = pin
    if not resolved_pin:
        resolved_pin = get_credential("token_pin")
    if not resolved_pin:
        resolved_pin = getpass.getpass("Token PIN: ")
        if resolved_pin:
            store_credential("token_pin", resolved_pin)
            console.print("[dim]PIN salvo no Keychain.[/dim]")

    if not resolved_pin:
        console.print("[red]Token PIN is required.[/red]")
        raise typer.Exit(code=1)

    # Detect cert/key paths

    cert_pem = "/tmp/juris_user_cert.pem"
    chain_pem = "/tmp/juris_chain.pem"
    key_uri = "pkcs11:token=TOKEN%20CERTDATA;object=p11%23e835efffba274fac;type=private"

    # Auto-export cert if not present
    if not __import__("os").path.exists(cert_pem):
        console.print("[yellow]Exporting certificate from token...[/yellow]")
        _export_token_cert(cert_pem, chain_pem, resolved_pin)

    pkcs11_config = PKCS11Config(
        pin=resolved_pin,
        cert_pem_path=cert_pem,
        chain_pem_path=chain_pem,
        key_uri=key_uri,
    )

    # Determine host/path from tribunal config
    from urllib.parse import urlparse

    endpoint = tribunal_cfg.service_url_override or tribunal_cfg.wsdl_url.replace("?wsdl", "")
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    path = parsed.path or "/pje/intercomunicacao"

    console.print(f"[bold]Fetching case (cert auth):[/bold] {cnj}")
    console.print(f"  Tribunal: {tribunal} ({host})")

    try:
        result = consultar_processo_pkcs11(
            host=host,
            path=path,
            pkcs11_config=pkcs11_config,
            id_consultante=cpf,
            senha_consultante=cpf,
            numero_cnj=str(cnj),
            mni_version=tribunal_cfg.mni_version,
            com_documentos=com_documentos,
        )
    except Exception as e:
        console.print(f"[red]MNI Error:[/red] {type(e).__name__}: {e}")
        raise typer.Exit(code=1) from e

    if not result.sucesso:
        console.print(f"[red]MNI returned error:[/red] {result.mensagem}")
        if "login" in result.mensagem.lower() or "autorizado" in result.mensagem.lower():
            from juris.core.credentials import delete_credential

            delete_credential("token_pin")
            console.print("[yellow]Stored PIN cleared. Re-run to enter new PIN.[/yellow]")
        raise typer.Exit(code=1)

    # Print results
    console.print(f"\n[bold green]Processo: {result.numero or str(cnj)}[/bold green]")
    console.print(f"  Classe: {result.classe or 'N/A'}")
    console.print(f"  Assunto: {result.assunto or 'N/A'}")
    if result.valor_causa:
        console.print(f"  Valor: R$ {result.valor_causa:,.2f}")
    console.print(f"  Órgão: {result.orgao_julgador or 'N/A'}")

    if result.partes:
        console.print(f"\n[bold]Partes ({len(result.partes)}):[/bold]")
        for p in result.partes:
            advs = f" (Advs: {', '.join(p['advogados'])})" if p.get("advogados") else ""
            console.print(f"  [{p.get('tipo', '?')}] {p.get('nome', '?')}{advs}")

    if result.movimentos:
        console.print(f"\n[bold]Movimentos ({len(result.movimentos)}):[/bold]")
        table = Table()
        table.add_column("Data", style="cyan", width=20)
        table.add_column("Código", width=8)
        table.add_column("Complemento")
        for m in result.movimentos[-10:]:
            table.add_row(m.get("data", ""), m.get("codigo", ""), (m.get("complemento", ""))[:80])
        console.print(table)

    if result.documentos:
        console.print(f"\n[bold]Documentos ({len(result.documentos)}):[/bold]")
        for d in result.documentos:
            console.print(f"  [{d.get('id', '')}] {d.get('tipo', '')}: {d.get('descricao', '')}")

    console.print(f"\n[dim]Raw XML: {len(result.raw_xml)} bytes[/dim]")


def _export_token_cert(cert_path: str, chain_path: str, pin: str) -> None:
    """Export user certificate and CA chain from the PKCS#11 token."""
    import subprocess

    pkcs11_module = "/usr/local/lib/libeTPkcs11.dylib"

    # Export all certs from token
    result = subprocess.run(
        [
            "p11tool", f"--provider={pkcs11_module}",
            "--list-all-certs",
            "pkcs11:token=TOKEN%20CERTDATA",
            "--outder",
        ],
        capture_output=True,
        env={**__import__("os").environ, "GNUTLS_PIN": pin},
    )

    # Use p11tool to export the specific user cert
    user_cert_uri = (
        "pkcs11:token=TOKEN%20CERTDATA;"
        "id=%79%70%44%5A%2D%53%6B%39%42%54%79%42%53%51%56%42%49%51%55%56%4D%49%45%31%42%55%6C%52%4A;"
        "object=p11%23e835efffba274fac;type=cert"
    )
    result = subprocess.run(
        ["p11tool", f"--provider={pkcs11_module}", "--export", user_cert_uri],
        capture_output=True,
        env={**__import__("os").environ, "GNUTLS_PIN": pin},
    )
    if result.returncode == 0 and result.stdout:
        with open(cert_path, "wb") as f:
            f.write(result.stdout)

    # Export CA chain (all certs except user cert)
    result = subprocess.run(
        [
            "p11tool", f"--provider={pkcs11_module}",
            "--export-chain", user_cert_uri,
        ],
        capture_output=True,
        env={**__import__("os").environ, "GNUTLS_PIN": pin},
    )
    if result.returncode == 0 and result.stdout:
        with open(chain_path, "wb") as f:
            f.write(result.stdout)


@app.command()
def track(
    numero_cnj: str = typer.Argument(..., help="Case number to track"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
) -> None:
    """Add a processo to the tracked list for overnight sync."""
    import json

    from juris.core.credentials import store_credential

    tracked = _get_tracked_processos()
    key = f"{tribunal}:{numero_cnj}"

    if key in {f"{p['tribunal']}:{p['numero_cnj']}" for p in tracked}:
        console.print(f"[yellow]Already tracking:[/yellow] {numero_cnj} ({tribunal})")
        return

    tracked.append({"numero_cnj": numero_cnj, "tribunal": tribunal})
    store_credential("tracked_processos", json.dumps(tracked))
    console.print(f"[green]Now tracking:[/green] {numero_cnj} ({tribunal})")
    console.print(f"[dim]Total tracked: {len(tracked)}[/dim]")


@app.command()
def untrack(
    numero_cnj: str = typer.Argument(..., help="Case number to stop tracking"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
) -> None:
    """Remove a processo from the tracked list."""
    import json

    from juris.core.credentials import store_credential

    tracked = _get_tracked_processos()
    key = f"{tribunal}:{numero_cnj}"
    new_tracked = [p for p in tracked if f"{p['tribunal']}:{p['numero_cnj']}" != key]

    if len(new_tracked) == len(tracked):
        console.print(f"[yellow]Not tracked:[/yellow] {numero_cnj}")
        return

    store_credential("tracked_processos", json.dumps(new_tracked))
    console.print(f"[green]Stopped tracking:[/green] {numero_cnj}")


@app.command()
def tracked() -> None:
    """List all tracked processos."""
    processos = _get_tracked_processos()
    if not processos:
        console.print("[yellow]No processos tracked. Use 'juris track <numero_cnj>' to add one.[/yellow]")
        return

    table = Table(title=f"Tracked Processos ({len(processos)})")
    table.add_column("#", style="dim", width=3)
    table.add_column("Tribunal", style="cyan", width=8)
    table.add_column("Número CNJ")

    for i, p in enumerate(processos, 1):
        table.add_row(str(i), p.get("tribunal", "?"), p.get("numero_cnj", "?"))

    console.print(table)


@app.command()
def pull_updates(
    tribunal: str = typer.Option(None, "--tribunal", "-t", help="Filter by tribunal (optional)"),
    cpf: str = typer.Option(None, "--cpf", help="CPF (required for MNI tribunals)"),
    senha: str = typer.Option(None, "--senha", "-s", help="Senha PJe (prompted if needed)"),
) -> None:
    """Pull updates for all tracked processos (differential sync)."""
    import asyncio

    from juris.jobs.overnight import run_overnight_sync
    from juris.persistence.local_db import LocalDB

    tracked_list = _get_tracked_processos()
    if not tracked_list:
        console.print("[yellow]No processos tracked. Use 'juris track <numero_cnj>' first.[/yellow]")
        raise typer.Exit(code=1)

    if tribunal:
        tracked_list = [p for p in tracked_list if p.get("tribunal") == tribunal]
        if not tracked_list:
            console.print(f"[yellow]No processos tracked for tribunal {tribunal}.[/yellow]")
            raise typer.Exit(code=1)

    db = LocalDB()

    # Build processos list with DB state for differential sync
    processos = []
    for p in tracked_list:
        cnj = p["numero_cnj"]
        tribunal_id = p.get("tribunal", "tjmg")

        # Get last sync time and known movements from DB
        last_sync = db.get_last_sync(cnj)
        proc = db.get_processo_by_cnj(cnj)
        known_keys = set()
        if proc:
            known_keys = db.get_known_movimento_keys(proc.id)

        processos.append({
            "numero_cnj": cnj,
            "tribunal_id": tribunal_id,
            "last_sync_at": last_sync,
            "known_movimento_keys": known_keys,
        })

    # Resolve credentials
    resolved_cpf = cpf or ""
    resolved_senha = senha or ""
    mni_tribunals = {p["tribunal_id"] for p in processos} - {"tjmg"}
    if mni_tribunals and not resolved_cpf:
        console.print("[yellow]MNI tribunals require --cpf. DataJud-only tribunals (tjmg) will still sync.[/yellow]")

    differential_count = sum(1 for p in processos if p["last_sync_at"] is not None)
    console.print(f"[bold]Syncing {len(processos)} processos...[/bold]")
    if differential_count:
        console.print(f"[dim]{differential_count} with prior sync (differential), {len(processos) - differential_count} full sync[/dim]")
    console.print()

    summary = asyncio.run(run_overnight_sync(
        processos=processos,
        cpf=resolved_cpf,
        senha=resolved_senha,
    ))

    # Persist results to LocalDB
    for result in summary.results:
        if not result.error and result.had_changes:
            # Persist new movimentos
            proc = db.get_processo_by_cnj(result.numero_cnj)
            if proc is None:
                proc_id = db.upsert_processo(result.numero_cnj, result.tribunal_id)
            else:
                proc_id = proc.id

            mov_dicts = [
                {
                    "data_hora": m.data_hora,
                    "tipo": m.tipo,
                    "codigo_nacional": m.codigo_nacional,
                    "complemento": m.complemento,
                    "descricao": m.descricao,
                    "id_movimento": m.id_movimento,
                    "categoria_semantica": None,
                }
                for m in result.new_movimentos
            ]
            new_count = db.insert_movimentos(proc_id, mov_dicts)

            db.log_sync(
                result.numero_cnj, result.tribunal_id, "mni",
                success=True, had_changes=True, new_movimentos=new_count,
            )
        elif not result.error:
            db.log_sync(
                result.numero_cnj, result.tribunal_id, "mni",
                success=True, had_changes=False,
            )

    # Print results
    for result in summary.results:
        if result.error:
            console.print(f"  [red]FAIL[/red] {result.numero_cnj}: {result.error}")
        elif result.had_changes:
            console.print(
                f"  [green]UPDATED[/green] {result.numero_cnj}: "
                f"{len(result.new_movimentos)} new movements"
            )
        else:
            console.print(f"  [dim]OK[/dim] {result.numero_cnj}: no changes")

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Checked: {summary.processos_checked}")
    console.print(f"  Updated: {summary.processos_updated}")
    console.print(f"  Failed:  {summary.processos_failed}")
    console.print(f"  New movements: {summary.new_movimentos_total}")
    console.print(f"  Duration: {summary.duration_seconds:.1f}s")
    console.print(f"  [dim]DB: {db.path}[/dim]")


def _get_tracked_processos() -> list[dict]:
    """Load tracked processos from credential storage."""
    import json

    from juris.core.credentials import get_credential

    raw = get_credential("tracked_processos")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


@app.command()
def analyze(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
    use_llm: bool = typer.Option(False, "--llm", help="Use LLM for ambiguous movements"),
    show_all: bool = typer.Option(False, "--all", "-a", help="Show all movements (not just actionable)"),
) -> None:
    """Analyze movements of a tracked processo (fetches from DataJud if needed)."""
    import asyncio

    from juris.agents.analyzer import analyze_processo
    from juris.datajud.client import consultar_processo as datajud_consulta
    from juris.datajud.parser import parse_datajud_processo
    from juris.mni.tpu import Urgencia

    console.print(f"[bold]Analyzing:[/bold] {numero_cnj} ({tribunal})")

    # Fetch processo from DataJud
    source = datajud_consulta(numero_cnj, tribunal)
    if source is None:
        console.print("[red]Case not found in DataJud.[/red]")
        raise typer.Exit(code=1)

    processo = parse_datajud_processo(source)

    if not processo.movimentos:
        console.print("[yellow]No movements to analyze.[/yellow]")
        return

    # Optionally set up LLM
    llm = None
    if use_llm:
        try:
            from juris.llm.ollama import OllamaLLM
            llm = OllamaLLM()
            console.print("[dim]LLM: Ollama (local) for ambiguous movements[/dim]")
        except Exception:
            console.print("[yellow]Ollama not available, using rules only.[/yellow]")

    analysis = asyncio.run(analyze_processo(
        numero_cnj=processo.numero_cnj,
        tribunal=tribunal,
        movimentos=processo.movimentos,
        llm=llm,
    ))

    # Print results
    console.print(f"\n[bold green]{analysis.summary}[/bold green]\n")

    items = analysis.analyzed if show_all else analysis.actionable
    if not items:
        console.print("[dim]Nenhuma ação pendente.[/dim]")
        return

    urgency_colors = {
        Urgencia.CRITICA: "red bold",
        Urgencia.ALTA: "red",
        Urgencia.MEDIA: "yellow",
        Urgencia.BAIXA: "dim",
        Urgencia.NENHUMA: "dim",
    }

    table = Table(title=f"{'Todas' if show_all else 'Ações Pendentes'} ({len(items)})")
    table.add_column("Data", style="cyan", width=12)
    table.add_column("Urgência", width=10)
    table.add_column("Categoria", width=18)
    table.add_column("Método", width=6)
    table.add_column("Recomendação")

    for r in items:
        style = urgency_colors.get(r.urgencia, "")
        table.add_row(
            r.data_hora.strftime("%Y-%m-%d"),
            f"[{style}]{r.urgencia.value}[/{style}]",
            r.categoria.value,
            r.metodo,
            r.recomendacao[:80],
        )
    console.print(table)

    console.print(f"\n[dim]Rule: {analysis.rule_classified} | LLM: {analysis.llm_calls} | Total: {analysis.total_movimentos}[/dim]")


@app.command()
def prazos(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
    show_all: bool = typer.Option(False, "--all", "-a", help="Include non-urgent deadlines"),
) -> None:
    """Compute deadlines for a processo (fetches + analyzes + computes prazos)."""
    import asyncio

    from juris.agents.analyzer import analyze_processo
    from juris.alerts.deadline_alerts import AlertLevel, generate_alerts
    from juris.datajud.client import consultar_processo as datajud_consulta
    from juris.datajud.parser import parse_datajud_processo
    from juris.prazo.engine import StatusPrazo, compute_prazos

    console.print(f"[bold]Computing deadlines:[/bold] {numero_cnj} ({tribunal})\n")

    # Fetch
    source = datajud_consulta(numero_cnj, tribunal)
    if source is None:
        console.print("[red]Case not found in DataJud.[/red]")
        raise typer.Exit(code=1)

    processo = parse_datajud_processo(source)
    if not processo.movimentos:
        console.print("[yellow]No movements found.[/yellow]")
        return

    # Analyze
    analysis = asyncio.run(analyze_processo(
        numero_cnj=processo.numero_cnj,
        tribunal=tribunal,
        movimentos=processo.movimentos,
    ))

    # Compute prazos
    report = compute_prazos(
        numero_cnj=processo.numero_cnj,
        tribunal=tribunal,
        analyses=analysis.analyzed,
    )

    if not report.prazos:
        console.print("[dim]Nenhum prazo pendente.[/dim]")
        return

    # Generate alerts
    alerts = generate_alerts(report, include_info=show_all)

    console.print(f"[bold]{report.summary}[/bold]\n")

    status_colors = {
        StatusPrazo.VENCIDO: "red bold",
        StatusPrazo.URGENTE: "red",
        StatusPrazo.PROXIMO: "yellow",
        StatusPrazo.ABERTO: "green",
    }

    table = Table(title=f"Prazos ({len(report.prazos)})")
    table.add_column("Vencimento", style="cyan", width=12)
    table.add_column("Status", width=10)
    table.add_column("Dias Úteis", width=10)
    table.add_column("Prazo", width=30)
    table.add_column("Base Legal", width=25)
    table.add_column("Ação")

    display_prazos = report.prazos if show_all else [p for p in report.prazos if p.status != StatusPrazo.ABERTO or p.dias_uteis_restantes <= 10]
    for p in display_prazos:
        style = status_colors.get(p.status, "")
        dias_str = f"{p.dias_uteis_restantes}d" if p.dias_uteis_restantes >= 0 else f"{p.dias_uteis_restantes}d"
        table.add_row(
            p.data_limite.strftime("%d/%m/%Y"),
            f"[{style}]{p.status.value}[/{style}]",
            dias_str,
            p.rule.nome,
            p.rule.base_legal,
            p.rule.tipo_acao.value,
        )
    console.print(table)

    # Print critical alerts
    if alerts.has_critical:
        console.print(f"\n[red bold]ALERTAS CRITICOS ({alerts.critical_count}):[/red bold]")
        for a in alerts.alerts:
            if a.level == AlertLevel.CRITICAL:
                console.print(f"  [red]{a.message}[/red]")


@app.command()
def sync(
    tribunal: str = typer.Option(None, "--tribunal", "-t", help="Filter by tribunal"),
) -> None:
    """Full sync pipeline via DataJud (no MNI). For MNI-capable sync, use 'juris overnight'."""
    import asyncio

    from juris.jobs.pipeline import run_pipeline
    from juris.persistence.local_db import LocalDB

    tracked_list = _get_tracked_processos()
    if not tracked_list:
        console.print("[yellow]No processos tracked. Use 'juris track <numero_cnj>' first.[/yellow]")
        raise typer.Exit(code=1)

    if tribunal:
        tracked_list = [p for p in tracked_list if p.get("tribunal") == tribunal]

    processos = [
        {"numero_cnj": p["numero_cnj"], "tribunal": p.get("tribunal", "tjmg")}
        for p in tracked_list
    ]

    db = LocalDB()
    console.print(f"[bold]Syncing {len(processos)} processos (full pipeline)...[/bold]")
    console.print(f"[dim]DB: {db.path}[/dim]\n")

    summary = asyncio.run(run_pipeline(processos, db=db))

    # Print results
    for r in summary.results:
        if r.error:
            console.print(f"  [red]FAIL[/red] {r.numero_cnj}: {r.error}")
        else:
            parts = [f"[green]OK[/green] {r.numero_cnj}"]
            if r.new_movimentos:
                parts.append(f"+{r.new_movimentos} mov")
            parts.append(f"{r.prazos_computed} prazos")
            if r.critical_alerts:
                parts.append(f"[red]{r.critical_alerts} alertas[/red]")
            console.print(f"  {' | '.join(parts)}")

            # Show critical alerts inline
            if r.alert_batch and r.alert_batch.has_critical:
                from juris.alerts.deadline_alerts import AlertLevel
                for a in r.alert_batch.alerts:
                    if a.level == AlertLevel.CRITICAL:
                        console.print(f"    [red]{a.short_message}[/red]")

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Succeeded: {summary.succeeded}/{summary.total}")
    console.print(f"  Critical alerts: {summary.total_critical_alerts}")
    console.print(f"  Duration: {summary.duration_seconds:.1f}s")


@app.command()
def overnight(
    tribunal: str = typer.Option(None, "--tribunal", "-t", help="Filter by tribunal"),
    cpf: str = typer.Option(None, "--cpf", help="CPF for MNI auth"),
    senha: str = typer.Option(None, "--senha", "-s", help="Senha PJe"),
    analyze: bool = typer.Option(True, "--analyze/--no-analyze", help="Run analysis after sync"),
    max_concurrent: int = typer.Option(10, "--max-concurrent", "-c", help="Max concurrent syncs"),
) -> None:
    """Full nightly pipeline: differential sync → analyze → prazos → alerts.

    This is the recommended command for production overnight runs.
    Uses MNI when available, falls back to DataJud.
    """
    import asyncio

    from juris.jobs.nightly import run_nightly
    from juris.persistence.local_db import LocalDB

    tracked_list = _get_tracked_processos()
    if not tracked_list:
        console.print("[yellow]No processos tracked. Use 'juris track <numero_cnj>' first.[/yellow]")
        raise typer.Exit(code=1)

    if tribunal:
        tracked_list = [p for p in tracked_list if p.get("tribunal") == tribunal]

    processos = [
        {"numero_cnj": p["numero_cnj"], "tribunal": p.get("tribunal", "tjmg")}
        for p in tracked_list
    ]

    db = LocalDB()
    resolved_cpf = cpf or ""
    resolved_senha = senha or ""

    console.print(f"[bold]Nightly pipeline: {len(processos)} processos[/bold]")
    console.print(f"[dim]DB: {db.path} | Concurrent: {max_concurrent} | Analyze: {analyze}[/dim]\n")

    summary = asyncio.run(run_nightly(
        processos=processos,
        db=db,
        cpf=resolved_cpf,
        senha=resolved_senha,
        max_concurrent=max_concurrent,
    ))

    # Print results
    for r in summary.results:
        if r.error:
            console.print(f"  [red]FAIL[/red] {r.numero_cnj}: {r.error}")
        else:
            parts = [f"[green]OK[/green] {r.numero_cnj}"]
            if r.new_movimentos:
                parts.append(f"+{r.new_movimentos} mov")
            if r.prazos_computed:
                parts.append(f"{r.prazos_computed} prazos")
            if r.critical_alerts:
                parts.append(f"[red]{r.critical_alerts} alertas[/red]")
            if not r.new_movimentos and r.success:
                parts.append("no changes")
            console.print(f"  {' | '.join(parts)}")

            # Show critical alerts inline
            if r.alert_batch and r.alert_batch.has_critical:
                from juris.alerts.deadline_alerts import AlertLevel
                for a in r.alert_batch.alerts:
                    if a.level == AlertLevel.CRITICAL:
                        console.print(f"    [red]{a.short_message}[/red]")

    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Succeeded: {summary.succeeded}/{summary.total}")
    if summary.total_critical_alerts:
        console.print(f"  [red]Critical alerts: {summary.total_critical_alerts}[/red]")
    console.print(f"  Duration: {summary.duration_seconds:.1f}s")


@app.command()
def dashboard() -> None:
    """Show a dashboard of all tracked processos with prazo status."""
    from datetime import date as date_type

    from juris.persistence.local_db import LocalDB

    db = LocalDB()
    processos = db.get_all_processos()

    if not processos:
        console.print("[yellow]No processos in local database. Run 'juris sync' first.[/yellow]")
        raise typer.Exit(code=1)

    # Header
    console.print(f"\n[bold]Dashboard — {len(processos)} processos[/bold]")
    console.print(f"[dim]DB: {db.path} | Date: {date_type.today().strftime('%d/%m/%Y')}[/dim]\n")

    # Processos table
    proc_table = Table(title="Processos")
    proc_table.add_column("#", style="dim", width=3)
    proc_table.add_column("Tribunal", style="cyan", width=8)
    proc_table.add_column("Número CNJ", width=25)
    proc_table.add_column("Classe", width=25)
    proc_table.add_column("Last Sync", width=18)
    proc_table.add_column("Prazos", width=20)

    for i, p in enumerate(processos, 1):
        prazos = db.get_pending_prazos(p.numero_cnj)
        vencidos = sum(1 for pr in prazos if pr.status == "vencido")
        urgentes = sum(1 for pr in prazos if pr.status in ("urgente", "proximo"))
        abertos = sum(1 for pr in prazos if pr.status == "aberto")

        prazo_parts = []
        if vencidos:
            prazo_parts.append(f"[red]{vencidos} venc[/red]")
        if urgentes:
            prazo_parts.append(f"[yellow]{urgentes} urg[/yellow]")
        if abertos:
            prazo_parts.append(f"[green]{abertos} ok[/green]")
        prazo_str = " | ".join(prazo_parts) if prazo_parts else "[dim]—[/dim]"

        sync_str = p.last_sync_at.strftime("%d/%m %H:%M") if p.last_sync_at else "[dim]never[/dim]"

        proc_table.add_row(
            str(i),
            p.tribunal_id,
            p.numero_cnj,
            (p.classe or "")[:25],
            sync_str,
            prazo_str,
        )

    console.print(proc_table)

    # Pending prazos summary
    all_prazos = db.get_pending_prazos()
    if all_prazos:
        console.print(f"\n[bold]Prazos Pendentes ({len(all_prazos)}):[/bold]")

        prazo_table = Table()
        prazo_table.add_column("Vencimento", style="cyan", width=12)
        prazo_table.add_column("Status", width=10)
        prazo_table.add_column("Processo", width=25)
        prazo_table.add_column("Prazo", width=30)
        prazo_table.add_column("Ação", width=15)

        status_colors = {
            "vencido": "red bold",
            "urgente": "red",
            "proximo": "yellow",
            "aberto": "green",
        }

        for pr in all_prazos[:20]:  # Top 20
            style = status_colors.get(pr.status, "")
            venc = pr.data_limite.strftime("%d/%m/%Y") if pr.data_limite else "?"
            prazo_table.add_row(
                venc,
                f"[{style}]{pr.status}[/{style}]",
                pr.numero_cnj,
                pr.rule_nome,
                pr.tipo_acao or "",
            )

        console.print(prazo_table)
    else:
        console.print("\n[dim]Nenhum prazo pendente.[/dim]")


@app.command()
def defesas(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
) -> None:
    """Analyze procedural defenses for a processo."""
    import asyncio

    from juris.datajud.client import consultar_processo as datajud_consulta
    from juris.datajud.parser import parse_datajud_processo
    from juris.defesas.analyzer import DefesaAnalyzer
    from juris.defesas.context import ProcessoContext

    console.print(f"[bold]Analyzing defenses:[/bold] {numero_cnj} ({tribunal})")

    source = datajud_consulta(numero_cnj, tribunal)
    if source is None:
        console.print("[red]Case not found in DataJud.[/red]")
        raise typer.Exit(code=1)

    processo = parse_datajud_processo(source)

    # Build ProcessoContext from ProcessoDomain
    movimentos_raw = [
        {"codigo": m.codigo_nacional, "data": m.data_hora.strftime("%Y-%m-%d")}
        for m in (processo.movimentos or [])
    ]
    partes_raw = [
        {"nome": p.nome, "tipo": p.tipo}
        for p in (processo.partes or [])
    ]

    context = ProcessoContext(
        numero_cnj=processo.numero_cnj,
        tribunal=tribunal,
        classe=processo.classe or "",
        ramo_justica="trabalho" if tribunal.startswith("trt") else "civel",
        data_ajuizamento=None,
        movimentos=movimentos_raw,
        partes=partes_raw,
        valor_causa=processo.valor_causa,
        assuntos=[processo.assunto] if processo.assunto else [],
    )

    analyzer = DefesaAnalyzer()
    report = asyncio.run(analyzer.analyze(context))

    console.print(f"\n[bold green]{report.summary}[/bold green]\n")

    if not report.defesas_identificadas:
        console.print("[dim]Nenhuma defesa processual identificada.[/dim]")
        return

    table = Table(title=f"Defesas ({len(report.defesas_identificadas)})")
    table.add_column("Tipo", style="cyan", width=25)
    table.add_column("Aplicavel", width=10)
    table.add_column("Confianca", width=10)
    table.add_column("Base Legal", width=25)
    table.add_column("Recomendacao")

    for d in report.defesas_identificadas:
        style = "green bold" if d.aplicavel else "dim"
        table.add_row(
            d.tipo.value,
            f"[{style}]{'SIM' if d.aplicavel else 'NAO'}[/{style}]",
            f"{d.confianca:.0%}",
            d.base_legal[:25] if d.base_legal else "",
            d.recomendacao[:60],
        )
    console.print(table)


@app.command()
def busca_parte(
    nome: str = typer.Option(None, "--nome", "-n", help="Nome da parte (e.g., 'FULANO DE TAL')"),
    cpf: str = typer.Option(None, "--cpf", "-c", help="CPF da parte (e.g., '123.456.789-00')"),
    oab: str = typer.Option(None, "--oab", "-o", help="OAB do advogado (e.g., 'SP123456')"),
    tribunal: str = typer.Option(None, "--tribunal", "-t", help="Tribunal específico (omita para buscar todos)"),
    justica: str = typer.Option(None, "--justica", "-j", help="Filtrar por ramo: estadual, trabalho, federal, superior"),
    max_results: int = typer.Option(10, "--max", "-m", help="Máximo de resultados por tribunal"),
    enrich: bool = typer.Option(True, "--enrich/--no-enrich", help="Enriquecer via DataJud"),
    use_cache: bool = typer.Option(True, "--cache/--no-cache", help="Usar cache de resultados"),
) -> None:
    """Search for processos by party name, CPF, or OAB across all channels.

    Queries ESAJ (12 TJs), eProc (TRF4+3 TJs), EJEF (TJMG), PROJUDI (TJPR),
    and DataJud (62+ tribunais) concurrently.
    """
    import asyncio

    from juris.busca.cache import BuscaCache
    from juris.busca.models import BuscaRequest
    from juris.busca.orchestrator import SearchOrchestrator
    from juris.busca.registry import ChannelRegistry

    if not nome and not cpf and not oab:
        console.print("[red]Informe ao menos --nome, --cpf ou --oab.[/red]")
        raise typer.Exit(code=1)

    # Build tribunal filter
    registry = ChannelRegistry()
    all_tribunais = registry.all_tribunais()
    tribunais_busca: list[str] | None = None

    if tribunal:
        tribunais_busca = [tribunal.lower()]
    elif justica:
        prefix_map = {
            "estadual": "tj",
            "trabalho": "trt",
            "federal": "trf",
        }
        prefix = prefix_map.get(justica.lower(), "")
        if prefix:
            tribunais_busca = [t for t in all_tribunais if t.startswith(prefix)]
        if tribunais_busca:
            console.print(f"[dim]Buscando em {len(tribunais_busca)} tribunais ({justica})...[/dim]")

    search_parts = []
    if nome:
        search_parts.append(f"Nome: {nome}")
    if cpf:
        search_parts.append(f"CPF: {cpf}")
    if oab:
        search_parts.append(f"OAB: {oab}")
    console.print(f"[bold]Busca por parte:[/bold] {' | '.join(search_parts)}")

    target_count = len(tribunais_busca) if tribunais_busca else len(all_tribunais)
    console.print(f"[dim]Buscando em {target_count} tribunais via 5 canais (ESAJ, eProc, EJEF, PROJUDI, DataJud)...[/dim]")

    request = BuscaRequest(
        nome=nome,
        cpf=cpf,
        oab=oab,
        tribunais=tribunais_busca,
        max_per_tribunal=max_results,
    )

    cache = BuscaCache() if use_cache else None
    orchestrator = SearchOrchestrator(
        registry=registry,
        cache=cache,
        enrich=enrich,
    )

    with console.status("[bold]Consultando canais..."):
        relatorio = asyncio.run(orchestrator.search(request))

    if not relatorio.resultados:
        console.print("[yellow]Nenhum processo encontrado.[/yellow]")
        if relatorio.tribunais_com_erro:
            console.print(f"[dim]Tribunais com erro: {', '.join(relatorio.tribunais_com_erro)}[/dim]")
        return

    console.print(
        f"\n[bold green]Encontrados: {relatorio.total_encontrado} processos[/bold green] "
        f"em {relatorio.duracao_segundos:.1f}s"
    )
    if relatorio.do_cache:
        console.print("[dim](resultado do cache)[/dim]")

    table = Table(title=f"Processos de {nome or cpf or oab}")
    table.add_column("#", style="dim", width=3)
    table.add_column("Tribunal", style="cyan", width=8)
    table.add_column("Número CNJ", width=27)
    table.add_column("Classe", width=25)
    table.add_column("Assunto", width=25)
    table.add_column("Ajuizamento", width=12)
    table.add_column("Fontes", width=15)
    table.add_column("Confiança", width=10)

    for i, r in enumerate(relatorio.resultados, 1):
        data_fmt = r.data_ajuizamento[:10] if len(r.data_ajuizamento) >= 10 else r.data_ajuizamento
        fontes_str = ",".join(f.value for f in r.fontes)
        conf_pct = f"{r.confianca:.0%}"
        conf_style = "green" if r.confianca >= 0.7 else "yellow" if r.confianca >= 0.5 else "dim"

        table.add_row(
            str(i),
            r.tribunal,
            r.numero_cnj,
            (r.classe or "")[:25],
            (r.assunto or "")[:25],
            data_fmt,
            fontes_str,
            f"[{conf_style}]{conf_pct}[/{conf_style}]",
        )

    console.print(table)

    # Show enrichment details
    enriched = [r for r in relatorio.resultados if r.enriquecido]
    if enriched:
        console.print(f"\n[bold]Dados enriquecidos ({len(enriched)} processos):[/bold]")
        for r in enriched[:5]:
            extras = []
            if r.movimentos_count:
                extras.append(f"{r.movimentos_count} movimentos")
            if r.valor_causa is not None:
                extras.append(f"R$ {r.valor_causa:,.2f}")
            if extras:
                console.print(f"  [cyan]{r.numero_cnj}[/cyan]: {', '.join(extras)}")

    # Show polo details
    results_with_polos = [r for r in relatorio.resultados if r.polo_ativo or r.polo_passivo]
    if results_with_polos:
        console.print(f"\n[bold]Detalhes das partes (primeiros {min(5, len(results_with_polos))}):[/bold]")
        for r in results_with_polos[:5]:
            console.print(f"\n  [cyan]{r.numero_cnj}[/cyan] ({r.tribunal})")
            if r.polo_ativo:
                for p in r.polo_ativo:
                    console.print(f"    [AT] {p}")
            if r.polo_passivo:
                for p in r.polo_passivo:
                    console.print(f"    [PA] {p}")

    if relatorio.tribunais_com_erro:
        console.print(f"\n[dim]Tribunais com erro: {', '.join(relatorio.tribunais_com_erro)}[/dim]")

    console.print("\n[dim]Para acompanhar um processo: juris track <numero_cnj> -t <tribunal>[/dim]")


@app.command()
def busca_canais() -> None:
    """List all search channels, supported tribunals, and circuit breaker status."""
    from juris.busca.models import FonteOrigem
    from juris.busca.registry import ChannelRegistry
    from juris.busca.retry import busca_circuit_breaker

    registry = ChannelRegistry()

    for fonte in FonteOrigem:
        tribunais = registry.tribunais_for_channel(fonte)
        if not tribunais:
            continue

        status_parts = []
        for tid in tribunais:
            state = busca_circuit_breaker.get_state(tid)
            if state.is_open:
                status_parts.append(f"[red]{tid}[/red]")
            elif state.failures > 0:
                status_parts.append(f"[yellow]{tid}[/yellow]")
            else:
                status_parts.append(f"[green]{tid}[/green]")

        console.print(f"\n[bold]{fonte.value.upper()}[/bold] ({len(tribunais)} tribunais)")
        console.print(f"  {', '.join(status_parts)}")


@app.command()
def tribunais() -> None:
    """List all registered tribunals."""
    from juris.mni.tribunais import list_tribunais

    table = Table(title="Tribunais Registrados")
    table.add_column("ID", style="cyan")
    table.add_column("Nome")
    table.add_column("Sistema")
    table.add_column("MNI")

    for t in list_tribunais():
        table.add_row(t.id, t.nome, t.sistema.value, t.mni_version)

    console.print(table)


@app.command()
def version() -> None:
    """Show juris version."""
    from juris import __version__

    console.print(f"juris v{__version__}")


repertory_app = typer.Typer(name="repertory", help="Jurisprudence corpus management.")
app.add_typer(repertory_app)


@repertory_app.command("ingest")
def repertory_ingest(
    source: str = typer.Option(None, "--source", "-s", help="Source key (omit for all). Use 'juris repertory sources' to list."),
    corpus_dir: str = typer.Option(None, "--corpus-dir", help="Path to corpus JSON directory"),
    include_superseded: bool = typer.Option(False, "--include-superseded", help="Include cancelada/superada entries"),
    limit: int = typer.Option(None, "--limit", "-l", help="Max items to ingest (class-based ingesters only)"),
) -> None:
    """Ingest jurisprudence seed data into the local vector store."""
    from pathlib import Path

    from juris.persistence.audit import AuditLog
    from juris.repertory.ingestion.registry import REGISTRY, ingest_source
    from juris.repertory.ingestion.seed_loader import SeedLoader
    from juris.repertory.vector_store import LocalFTSStore

    if source and source not in REGISTRY:
        console.print(f"[red]Unknown source: {source}[/red]")
        console.print(f"Available: {', '.join(REGISTRY)}")
        raise typer.Exit(code=1)

    fts_path = Path.home() / ".juris" / "repertory.db"
    fts_path.parent.mkdir(parents=True, exist_ok=True)
    store = LocalFTSStore(db_path=fts_path)

    label = REGISTRY[source].label if source else "all sources"
    console.print(f"[bold]Ingesting corpus seed data ({label})...[/bold]")
    console.print(f"[dim]DB: {fts_path}[/dim]")
    if include_superseded:
        console.print("[dim]Including superseded/cancelada entries[/dim]")

    if source:
        entry = REGISTRY[source]
        # Class-based ingester (e.g., tjdft-modelos, stf-landmark)
        if entry.source_dir or entry.ingester_class:
            dir_path = Path(corpus_dir) if corpus_dir else Path(__file__).resolve().parents[3]
            result = ingest_source(source, dir_path / "data" / "corpus", store, limit=limit)
        else:
            dir_path = Path(corpus_dir) if corpus_dir else None
            loader = SeedLoader(corpus_dir=dir_path, include_superseded=include_superseded)
            audit_path = fts_path.parent / "audit.jsonl"
            audit = AuditLog(path=audit_path)
            result = loader.ingest(store, audit_log=audit)
    else:
        dir_path = Path(corpus_dir) if corpus_dir else None
        loader = SeedLoader(corpus_dir=dir_path, include_superseded=include_superseded)
        audit_path = fts_path.parent / "audit.jsonl"
        audit = AuditLog(path=audit_path)
        result = loader.ingest(store, audit_log=audit)

    console.print(f"  Fetched: {result.total_fetched} sources")
    console.print(f"  Chunks:  {result.total_chunks}")
    console.print(f"  Stored:  {result.total_embedded}")
    console.print("[green]Done.[/green]")


@repertory_app.command("sources")
def repertory_sources(
    corpus_dir: str = typer.Option(None, "--corpus-dir", help="Path to corpus JSON directory"),
    include_superseded: bool = typer.Option(False, "--include-superseded", help="Count cancelada/superada entries"),
) -> None:
    """List all registered corpus sources with entry counts."""
    from pathlib import Path

    from rich.table import Table as RichTable

    from juris.repertory.ingestion.registry import count_source_entries, get_available_sources
    from juris.repertory.ingestion.seed_loader import _DEFAULT_CORPUS_DIR

    dir_path = Path(corpus_dir) if corpus_dir else _DEFAULT_CORPUS_DIR
    sources = get_available_sources()
    counts = count_source_entries(dir_path, include_superseded=include_superseded)

    table = RichTable(title="Registered Corpus Sources")
    table.add_column("Key", style="cyan", width=18)
    table.add_column("Label", width=30)
    table.add_column("Tribunal", width=10)
    table.add_column("Hierarquia", justify="center", width=10)
    table.add_column("Entries", justify="right", width=8)
    table.add_column("File", width=35)

    total = 0
    for src in sources:
        count = counts.get(src.key, 0)
        total += count
        table.add_row(
            src.key,
            src.label,
            src.tribunal,
            str(src.hierarquia),
            str(count) if count > 0 else "[dim]0[/dim]",
            src.seed_file,
        )

    console.print(table)
    console.print(f"\n[bold]Total entries: {total}[/bold]")


@repertory_app.command("verify")
def repertory_verify() -> None:
    """Run diagnostic verification queries against the ingested corpus."""
    from pathlib import Path

    from juris.repertory.vector_store import LocalFTSStore

    fts_path = Path.home() / ".juris" / "repertory.db"
    if not fts_path.exists():
        console.print("[yellow]No corpus ingested yet. Run 'juris repertory ingest' first.[/yellow]")
        raise typer.Exit(code=1)

    store = LocalFTSStore(db_path=fts_path)

    queries = [
        ("prescrição quinquenal", 10),
        ("desconsideração da personalidade jurídica", 5),
        ("responsabilidade objetiva do Estado", 8),
        ("FGTS correção", 2),
        ("aviso prévio proporcional", 2),
        ("consumidor banco", 3),
        ("repercussão geral tese", 5),
    ]

    all_passed = True
    for query, min_results in queries:
        results = store.search_text(query, top_k=20)
        status = "[green]PASS[/green]" if len(results) >= min_results else "[red]FAIL[/red]"
        if len(results) < min_results:
            all_passed = False
        console.print(f"  {status} \"{query}\" — {len(results)} results (min: {min_results})")

    if all_passed:
        console.print("\n[green bold]All verification queries passed.[/green bold]")
    else:
        console.print("\n[yellow]Some queries did not meet minimum thresholds.[/yellow]")
        raise typer.Exit(code=1)


@repertory_app.command("search")
def repertory_search(
    query: str = typer.Argument(..., help="Search query"),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Number of results"),
) -> None:
    """Search the jurisprudence corpus."""
    from pathlib import Path

    from rich.table import Table as RichTable

    from juris.repertory.vector_store import LocalFTSStore

    fts_path = Path.home() / ".juris" / "repertory.db"
    if not fts_path.exists():
        console.print("[yellow]No corpus ingested yet. Run 'juris repertory ingest' first.[/yellow]")
        raise typer.Exit(code=1)
    store = LocalFTSStore(db_path=fts_path)
    results = store.search_text(query, top_k=top_k)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = RichTable(title=f"Results for: {query}")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", width=8)
    table.add_column("Source", width=30)
    table.add_column("Text", width=60)

    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            f"{r.score:.4f}",
            r.source_id[:30],
            r.text[:60] + "..." if len(r.text) > 60 else r.text,
        )

    console.print(table)


@repertory_app.command("poll-noticias")
def repertory_poll_noticias() -> None:
    """Poll court RSS feeds for new noticias (placeholder — wired in Phase 6)."""
    console.print("[yellow]poll-noticias not yet implemented. Will be wired in Phase 6.[/yellow]")


@repertory_app.command("ingest-peticoes")
def repertory_ingest_peticoes(
    directory: str = typer.Option("storage/peticoes_modelo", "--dir", "-d", help="Directory with model petition PDFs"),
) -> None:
    """Process PDF petitions from a directory and extract templates."""
    import asyncio
    from pathlib import Path

    from juris.repertory.ingestion.pdf_peticoes import ingest_peticoes, scan_peticoes_dir

    dir_path = Path(directory)
    pdfs = scan_peticoes_dir(dir_path)

    if not pdfs:
        console.print(f"[yellow]No PDF files found in {directory}.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"[bold]Found {len(pdfs)} PDF petitions in {directory}[/bold]")

    try:
        from juris.llm.ollama import OllamaLLM

        llm = OllamaLLM()
    except Exception:
        console.print("[red]Ollama not available. LLM is required for extraction.[/red]")
        raise typer.Exit(code=1)

    templates = asyncio.run(ingest_peticoes(directory=dir_path, llm=llm))

    if not templates:
        console.print("[yellow]No templates extracted.[/yellow]")
        return

    table = Table(title=f"Extracted Templates ({len(templates)})")
    table.add_column("ID", style="cyan")
    table.add_column("Tipo", width=20)
    table.add_column("Titulo", width=40)
    table.add_column("Seções", width=8)

    for t in templates:
        table.add_row(t.id, t.tipo.value, t.titulo[:40], str(len(t.estrutura)))

    console.print(table)


@app.command()
def review(
    path: str = typer.Argument(..., help="Path to petition (PDF or Markdown)"),
    case: str = typer.Option(None, "--case", "-c", help="CNJ number for case context"),
    tribunal: str = typer.Option(None, "--tribunal", "-t", help="Tribunal ID"),
    output: str = typer.Option(None, "--output", "-o", help="Save report to file"),
    cloud: bool = typer.Option(False, "--cloud", help="Use Claude instead of local LLM"),
    dimensions: str = typer.Option(None, "--dimensions", "-d", help="Comma-separated dimensions to analyze"),
) -> None:
    """Review a petition and produce structured critique."""
    import asyncio
    from pathlib import Path

    from juris.review.extractor import extract_text_from_file
    from juris.review.models import ReviewDimension, ReviewRequest

    petition_path = Path(path)
    if not petition_path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(code=1)

    # Extract text
    try:
        text = extract_text_from_file(petition_path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e

    if not text.strip():
        console.print("[yellow]Petition file is empty.[/yellow]")
        raise typer.Exit(code=1)

    # Set up LLM
    if cloud:
        try:
            from juris.config import get_settings
            from juris.llm.claude import ClaudeLLM
            settings = get_settings()
            if not settings.anthropic_api_key:
                console.print("[red]ANTHROPIC_API_KEY not configured. Set it in .env or environment.[/red]")
                raise typer.Exit(code=1)
            llm = ClaudeLLM(api_key=settings.anthropic_api_key.get_secret_value())
            console.print("[dim]LLM: Claude (cloud)[/dim]")
        except typer.Exit:
            raise
        except Exception:
            console.print("[red]Claude not available. Check ANTHROPIC_API_KEY.[/red]")
            raise typer.Exit(code=1)
    else:
        try:
            from juris.llm.ollama import OllamaLLM
            llm = OllamaLLM()
            console.print("[dim]LLM: Ollama (local)[/dim]")
        except Exception:
            console.print("[red]Ollama not available.[/red]")
            raise typer.Exit(code=1)

    # Set up retriever
    from juris.repertory.embeddings import LegalEmbedder
    from juris.repertory.retrieval.hybrid import HybridRetriever
    from juris.repertory.retrieval.service import RepertoryService
    from juris.repertory.vector_store import LocalFTSStore

    fts_path = Path.home() / ".juris" / "repertory.db"
    if not fts_path.exists():
        console.print("[yellow]No corpus ingested. Run 'juris repertory ingest' first.[/yellow]")
        console.print("[dim]Proceeding without retrieval context...[/dim]")

    store = LocalFTSStore(db_path=fts_path)
    embedder = LegalEmbedder()  # lazy-loads model; returns None if unavailable

    retriever = HybridRetriever(
        dense_store=store,
        sparse_store=store,
        embedder=embedder,
    )
    service = RepertoryService(retriever=retriever)

    # Set up audit
    from juris.persistence.audit import AuditLog

    audit_path = Path.home() / ".juris" / "audit.jsonl"
    audit = AuditLog(path=audit_path)

    # Parse dimensions
    dims = None
    if dimensions:
        dims = [ReviewDimension(d.strip()) for d in dimensions.split(",")]

    # Build request
    from juris.review.extractor import detect_petition_type

    petition_type = detect_petition_type(text)
    request = ReviewRequest(
        petition_text=text,
        petition_type=petition_type,
        numero_cnj=case,
        tribunal=tribunal,
    )

    console.print(f"[bold]Reviewing:[/bold] {petition_path.name}")
    if petition_type:
        console.print(f"[dim]Detected type: {petition_type}[/dim]")
    if case:
        console.print(f"[dim]Case: {case}[/dim]")

    # Run review
    from juris.review.reviewer import ReviewerAgent

    agent = ReviewerAgent(llm=llm, retriever=service, audit_log=audit)

    with console.status("[bold]Analyzing petition..."):
        report = asyncio.run(agent.review(request, dimensions=dims))

    # Print summary
    console.print(f"\n[bold green]Review complete[/bold green] ({report.duration_seconds:.1f}s)")
    console.print(f"  Critical: {report.critical_count} | Important: {report.important_count} | Suggestions: {report.suggestion_count}")
    console.print(f"  Citations: {len(report.citations_found)} | LLM calls: {report.llm_calls}")

    # Print issues
    if report.issues:
        severity_colors = {
            "critical": "red bold",
            "important": "yellow",
            "suggestion": "dim",
        }
        console.print()
        for issue in report.issues:
            style = severity_colors.get(issue.severity.value, "")
            console.print(f"  [{style}][{issue.severity.value.upper()}][/{style}] {issue.title}")
            console.print(f"    [dim]{issue.dimension.value}:[/dim] {issue.description[:120]}")
            if issue.suggestion:
                console.print(f"    [green]Sugestao:[/green] {issue.suggestion[:120]}")

    # Save report
    md = report.to_markdown()
    if output:
        output_path = Path(output)
        output_path.write_text(md, encoding="utf-8")
        console.print(f"\n[green]Report saved to:[/green] {output_path}")
    else:
        console.print(f"\n{md}")


@app.command()
def draft(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format"),
    tipo: str = typer.Argument(..., help="Petition type (contestacao, inicial, apelacao, etc.)"),
    thesis: str = typer.Option(None, "--thesis", "-T", help="Explicit thesis statement"),
    instructions: str = typer.Option("", "--instructions", "-i", help="Custom instructions for the LLM"),
    cloud: bool = typer.Option(False, "--cloud", help="Use Claude instead of local LLM"),
    output: str = typer.Option(None, "--output", "-o", help="Save draft files to directory"),
    skip_review: bool = typer.Option(False, "--skip-review", help="Skip post-generation review"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
) -> None:
    """Generate a petition draft with grounded citations."""
    import asyncio
    from pathlib import Path

    from rich.panel import Panel

    from juris.agents.citation_verifier import MarkerCitationVerifier
    from juris.agents.drafter import DrafterAgent, DraftRequest
    from juris.agents.researcher import Researcher
    from juris.defesas.analyzer import DefesaAnalyzer
    from juris.defesas.context import ProcessoContext
    from juris.persistence.audit import AuditLog
    from juris.repertory.peticoes.models import TipoPeticao
    from juris.repertory.retrieval.service import RepertoryService

    # Validate tipo_peticao
    try:
        tipo_peticao = TipoPeticao(tipo)
    except ValueError as e:
        valid = ", ".join(t.value for t in TipoPeticao)
        console.print(f"[red]Tipo invalido: '{tipo}'. Opcoes: {valid}[/red]")
        raise typer.Exit(code=1) from e

    # Set up LLM (same pattern as review command)
    if cloud:
        console.print(
            "[yellow bold]AVISO PII:[/yellow bold] --cloud envia dados do processo para API externa. "
            "Use apenas se o caso nao contiver dados sensiveis ou se houver autorizacao expressa."
        )
        try:
            from juris.config import get_settings
            from juris.llm.claude import ClaudeLLM
            settings = get_settings()
            if not settings.anthropic_api_key:
                console.print("[red]ANTHROPIC_API_KEY not configured. Set it in .env or environment.[/red]")
                raise typer.Exit(code=1)
            llm = ClaudeLLM(api_key=settings.anthropic_api_key.get_secret_value())
            console.print("[dim]LLM: Claude (cloud)[/dim]")
        except typer.Exit:
            raise
        except Exception as exc:
            console.print("[red]Claude not available. Check ANTHROPIC_API_KEY.[/red]")
            raise typer.Exit(code=1) from exc
    else:
        try:
            from juris.llm.ollama import OllamaLLM
            llm = OllamaLLM()
            console.print("[dim]LLM: Ollama (local)[/dim]")
        except Exception as exc:
            console.print("[red]Ollama not available. Is the server running?[/red]")
            raise typer.Exit(code=1) from exc

    # Set up retrieval infrastructure
    try:
        from juris.repertory.embeddings import LegalEmbedder
        from juris.repertory.retrieval.hybrid import HybridRetriever
        from juris.repertory.retrieval.reranker import CrossEncoderReranker
        from juris.repertory.vector_store import LocalFTSStore

        embedder = LegalEmbedder()
        fts_store = LocalFTSStore(Path("data/repertory.db"))
        reranker = CrossEncoderReranker()
        retriever = HybridRetriever(
            dense_store=fts_store,
            sparse_store=fts_store,
            embedder=embedder,
            reranker=reranker,
        )
        repertory = RepertoryService(retriever)
    except Exception as e:
        console.print(f"[red]Failed to initialize retrieval: {e}[/red]")
        raise typer.Exit(code=1) from e

    # Set up audit log
    audit = AuditLog(Path("data/audit.jsonl"))

    # Set up components
    researcher = Researcher(repertory=repertory, llm=llm, audit=audit)
    verifier = MarkerCitationVerifier(repertory=repertory)
    defesa_analyzer = DefesaAnalyzer(llm=llm)

    reviewer = None
    if not skip_review:
        from juris.review.reviewer import ReviewerAgent
        reviewer = ReviewerAgent(llm=llm, retriever=repertory, audit_log=audit)

    agent = DrafterAgent(
        llm=llm,
        repertory=repertory,
        researcher=researcher,
        verifier=verifier,
        reviewer=reviewer,
        audit=audit,
        defesa_analyzer=defesa_analyzer,
    )

    # Build minimal ProcessoContext
    context = ProcessoContext(
        numero_cnj=numero_cnj,
        tribunal=tribunal,
        classe="",
    )

    request = DraftRequest(
        numero_cnj=numero_cnj,
        tribunal=tribunal,
        tipo_peticao=tipo_peticao,
        thesis=thesis,
        custom_instructions=instructions,
        use_cloud_llm=cloud,
    )

    console.print(f"[bold]Generating {tipo} draft for {numero_cnj}...[/bold]")

    try:
        result = asyncio.run(agent.draft(request, context))
    except Exception as e:
        console.print(f"[red]Draft generation failed: {e}[/red]")
        raise typer.Exit(code=1) from e

    # Display results
    console.print()
    console.print(result.draft_markdown)

    if result.contraponto_section:
        console.print()
        console.print(Panel(
            result.contraponto_section,
            title="[bold yellow]CONTRAPONTO PREVISTO[/bold yellow]",
            border_style="yellow",
        ))

    # Summary footer
    console.print()
    console.print("[bold]--- Resumo ---[/bold]")
    console.print(f"Cobertura: {result.research_summary}")
    console.print(f"Citacoes: {len(result.citations_used)}")
    console.print(f"Revisoes: {result.revisions}")
    console.print(f"Duracao: {result.total_duration_seconds:.1f}s")
    if result.reviewer_report:
        rr = result.reviewer_report
        console.print(
            f"Revisor: {rr.critical_count} criticos, "
            f"{rr.important_count} importantes, "
            f"{rr.suggestion_count} sugestoes"
        )

    # Save to file if requested
    if output:
        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        draft_path = out_dir / "draft.md"
        draft_path.write_text(result.draft_markdown, encoding="utf-8")
        console.print(f"[green]Draft saved to {draft_path}[/green]")

        if result.contraponto_section:
            contra_path = out_dir / "draft.contraponto.md"
            contra_path.write_text(result.contraponto_section, encoding="utf-8")
            console.print(f"[green]Contraponto saved to {contra_path}[/green]")


alerts_app = typer.Typer(name="alerts", help="Deadline alert management.")
app.add_typer(alerts_app)


@alerts_app.command("send")
def alerts_send() -> None:
    """Send pending deadline alerts via email."""
    import asyncio

    from juris.alerts.delivery import AlertDelivery, AlertEmailConfig
    from juris.config import get_settings
    from juris.persistence.local_db import LocalDB

    settings = get_settings()

    # Build SMTP config
    to_list = [a.strip() for a in settings.alert_to_addresses.split(",") if a.strip()]
    smtp_config = AlertEmailConfig(
        smtp_host=settings.alert_smtp_host,
        smtp_port=settings.alert_smtp_port,
        smtp_user=settings.alert_smtp_user,
        smtp_password=settings.alert_smtp_password.get_secret_value() if settings.alert_smtp_password else "",
        from_address=settings.alert_from_address,
        to_addresses=to_list,
    )

    if not smtp_config.is_configured:
        console.print("[red]SMTP not configured. Set ALERT_SMTP_HOST, ALERT_FROM_ADDRESS, ALERT_TO_ADDRESSES.[/red]")
        raise typer.Exit(code=1)

    db = LocalDB()
    delivery = AlertDelivery(smtp_config)

    # Get all processos with pending prazos
    processos = db.get_all_processos()
    if not processos:
        console.print("[yellow]No processos in database.[/yellow]")
        return

    sent = 0
    failed = 0
    for proc in processos:
        pending = db.get_pending_prazos(proc.numero_cnj)
        if not pending:
            continue

        # Build a minimal AlertBatch from pending prazos
        from datetime import date

        from juris.alerts.deadline_alerts import AlertBatch, AlertLevel, DeadlineAlert

        alerts_list = []
        for pr in pending:
            if pr.status in ("vencido", "urgente", "proximo"):
                level = AlertLevel.CRITICAL if pr.status in ("vencido", "urgente") else AlertLevel.WARNING
                alerts_list.append(DeadlineAlert(
                    prazo=pr,
                    level=level,
                    message=f"{pr.rule_nome}: {pr.status}",
                ))

        if not alerts_list:
            continue

        batch = AlertBatch(
            numero_cnj=proc.numero_cnj,
            tribunal=proc.tribunal_id,
            generated_at=date.today(),
            alerts=alerts_list,
        )

        success = asyncio.run(delivery.send_alert_batch(batch))
        if success:
            sent += 1
        else:
            failed += 1

    console.print(f"[bold]Alerts sent:[/bold] {sent} processos | [red]Failed:[/red] {failed}")


benchmark_app = typer.Typer(name="benchmark", help="Retrieval quality benchmark tools.")
app.add_typer(benchmark_app)


@benchmark_app.command("curate")
def benchmark_curate(
    path: str = typer.Argument("data/benchmark_pairs.json", help="Path to benchmark pairs JSON"),
) -> None:
    """Interactive curation of extracted benchmark pairs."""
    from pathlib import Path

    from juris.benchmark.extractor import load_pairs, save_pairs

    pairs_path = Path(path)
    if not pairs_path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(code=1)

    pairs = load_pairs(pairs_path)
    if not pairs:
        console.print("[yellow]No pairs found in file.[/yellow]")
        return

    pending = [p for p in pairs if p.status == "pending"]
    console.print(f"[bold]Curating benchmark pairs:[/bold] {len(pending)} pending / {len(pairs)} total\n")

    for i, pair in enumerate(pending):
        console.print(f"\n[bold cyan]--- Pair {i + 1}/{len(pending)} ---[/bold cyan]")
        console.print(f"  [bold]Thesis:[/bold] {pair.thesis}")
        console.print(f"  [bold]Sources:[/bold] {', '.join(pair.expected_source_ids)}")
        console.print(f"  [bold]Confidence:[/bold] {pair.confidence:.2f}")
        console.print(f"  [bold]Provenance:[/bold] {pair.provenance}")
        if pair.paraphrases:
            console.print(f"  [bold]Paraphrases:[/bold] {'; '.join(pair.paraphrases)}")

        choice = typer.prompt("  [a]ccept / [r]eject / [s]kip / [q]uit", default="s")
        if choice.lower().startswith("a"):
            pair.status = "accepted"
            console.print("  [green]Accepted[/green]")
        elif choice.lower().startswith("r"):
            reason = typer.prompt("  Rejection reason", default="")
            pair.status = "rejected"
            pair.rejection_reason = reason
            console.print("  [red]Rejected[/red]")
        elif choice.lower().startswith("q"):
            break
        else:
            console.print("  [dim]Skipped[/dim]")

    save_pairs(pairs, pairs_path)
    accepted = sum(1 for p in pairs if p.status == "accepted")
    rejected = sum(1 for p in pairs if p.status == "rejected")
    still_pending = sum(1 for p in pairs if p.status == "pending")
    console.print(f"\n[bold]Saved:[/bold] {accepted} accepted, {rejected} rejected, {still_pending} pending")


@benchmark_app.command("run")
def benchmark_run(
    path: str = typer.Argument("data/benchmark_pairs.json", help="Path to benchmark pairs JSON"),
    top_k: int = typer.Option(3, "--top-k", "-k", help="Top-K for recall calculation"),
) -> None:
    """Run retrieval benchmark on curated pairs and report recall@K."""
    from pathlib import Path

    from juris.benchmark.extractor import load_curated_pairs

    pairs_path = Path(path)
    if not pairs_path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(code=1)

    pairs = load_curated_pairs(pairs_path)
    if not pairs:
        console.print("[yellow]No accepted pairs found. Run 'juris benchmark curate' first.[/yellow]")
        return

    # Set up retrieval
    try:
        from juris.repertory.embeddings import LegalEmbedder
        from juris.repertory.retrieval.hybrid import HybridRetriever
        from juris.repertory.retrieval.service import RepertoryService
        from juris.repertory.vector_store import LocalFTSStore

        fts_path = Path.home() / ".juris" / "repertory.db"
        store = LocalFTSStore(db_path=fts_path)
        embedder = LegalEmbedder()
        retriever = HybridRetriever(dense_store=store, sparse_store=store, embedder=embedder)
        service = RepertoryService(retriever=retriever)
    except Exception as e:
        console.print(f"[red]Failed to initialize retrieval: {e}[/red]")
        raise typer.Exit(code=1) from e

    console.print(f"[bold]Running benchmark:[/bold] {len(pairs)} pairs, recall@{top_k}\n")

    hits = 0
    total = 0
    for pair in pairs:
        queries = [pair.thesis] + pair.paraphrases
        found_ids: set[str] = set()

        for q in queries:
            results = service.search_jurisprudencia(query=q, top_k=top_k)
            found_ids.update(r.source_id for r in results)

        expected = set(pair.expected_source_ids)
        if expected & found_ids:
            hits += 1
        total += 1

    recall = hits / total if total else 0.0
    console.print(f"[bold]Recall@{top_k}:[/bold] {recall:.1%} ({hits}/{total})")
    if recall < 0.7:
        console.print("[yellow]Below 70% target. Consider adding more corpus data or tuning retrieval.[/yellow]")
    else:
        console.print("[green]Above 70% target.[/green]")


@app.command(name="file")
def file_petition(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format"),
    draft_path_or_tipo: str = typer.Argument(
        ..., help="Path to draft markdown file, or petition type (loads most recent draft)"
    ),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t", help="Tribunal ID"),
    cpf: str = typer.Option(..., "--cpf", help="CPF do advogado"),
    tipo_doc: str = typer.Option("manifestacao", "--tipo-doc", help="Tipo de documento para protocolo"),
    skip_preflight: bool = typer.Option(False, "--skip-preflight", help="Skip pre-flight checks"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Render and check only — no signing or filing"),
    prazo_override: str | None = typer.Option(None, "--prazo-override", help="Justificativa for filing past deadline"),
    senha: str | None = typer.Option(None, "--senha", "-s", help="Senha PJe (prompted + saved if omitted)"),
    pin: str | None = typer.Option(None, "--pin", help="Token PIN (prompted + saved if omitted)"),
) -> None:
    """Sign and file a petition via MNI.

    Renders a draft to PDF, runs pre-flight checks, signs with A3 token,
    files via MNI, and stores the receipt.

    Use --dry-run for a side-effect-free preview.
    """
    import asyncio
    from pathlib import Path as FilePath

    from juris.core.credentials import get_credential, store_credential
    from juris.persistence.audit import AuditLog
    from juris.persistence.filing_receipt import FilingReceiptStore
    from juris.signing.filing import FilingOrchestrator, FilingRequest

    # 1. Load draft markdown
    draft_path = FilePath(draft_path_or_tipo)
    if draft_path.exists() and draft_path.is_file():
        draft_markdown = draft_path.read_text(encoding="utf-8")
        tipo_peticao = draft_path.stem
        console.print(f"[dim]Loaded draft from {draft_path} ({len(draft_markdown)} chars)[/dim]")
    else:
        # Treat as tipo_peticao, look for most recent draft in ~/.juris/drafts/
        tipo_peticao = draft_path_or_tipo
        drafts_dir = FilePath.home() / ".juris" / "drafts" / numero_cnj.replace(".", "_").replace("-", "_")
        if drafts_dir.exists():
            drafts = sorted(drafts_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if drafts:
                draft_markdown = drafts[0].read_text(encoding="utf-8")
                console.print(f"[dim]Loaded most recent draft: {drafts[0].name}[/dim]")
            else:
                console.print(f"[red]No drafts found in {drafts_dir}[/red]")
                raise typer.Exit(code=1)
        else:
            console.print(f"[red]'{draft_path_or_tipo}' is not a file and no drafts found.[/red]")
            console.print("[dim]Provide a path to a markdown file or run 'juris draft' first.[/dim]")
            raise typer.Exit(code=1)

    # 2. Resolve PIN
    resolved_pin = pin
    if not resolved_pin:
        resolved_pin = get_credential("token_pin")
    if not resolved_pin:
        import getpass

        resolved_pin = getpass.getpass("PIN do token A3: ")
        if resolved_pin:
            store_credential("token_pin", resolved_pin)
            console.print("[dim]PIN salvo no Keychain.[/dim]")

    if not resolved_pin:
        console.print("[red]PIN do token é obrigatório.[/red]")
        raise typer.Exit(code=1)

    # 3. Resolve senha
    resolved_senha = _get_senha(tribunal, cpf, senha)
    from juris.mni.auth import AuthStrategy, PasswordAuth

    mni_auth = PasswordAuth(cpf=cpf, senha=resolved_senha)

    # 4. Setup components
    juris_dir = FilePath.home() / ".juris"
    audit = AuditLog(juris_dir / "audit.jsonl")
    receipt_store = FilingReceiptStore(juris_dir / "filings", audit)

    # 5. MNI client factory
    def mni_client_factory(tribunal_id: str, auth: AuthStrategy) -> object:
        from juris.mni.client import get_mni_client

        return get_mni_client(tribunal_id, auth)

    # 6. Build filing request
    filing_request = FilingRequest(
        numero_cnj=numero_cnj,
        tribunal=tribunal,
        tipo_documento=tipo_doc,
        draft_markdown=draft_markdown,
        tipo_peticao=tipo_peticao,
        cpf=cpf,
        senha=resolved_senha,
        skip_preflight=skip_preflight,
        dry_run=dry_run,
        prazo_override=prazo_override,
    )

    # 7. Initialize signer and run pipeline
    from juris.signing.pades import PAdESSigner

    pkcs11_module = "/usr/local/lib/libeTPkcs11.dylib"
    token_label = "TOKEN CERTDATA"

    try:
        if dry_run and skip_preflight:
            # Dry-run without preflight doesn't need the hardware token
            from unittest.mock import MagicMock

            mock_signer = MagicMock(spec=PAdESSigner)
            orchestrator = FilingOrchestrator(
                signer=mock_signer,
                audit=audit,
                receipt_store=receipt_store,
                mni_client_factory=mni_client_factory,
                mni_auth=mni_auth,
            )
            result = asyncio.run(orchestrator.file(filing_request))
        else:
            with PAdESSigner(pkcs11_module, token_label, resolved_pin) as signer:
                orchestrator = FilingOrchestrator(
                    signer=signer,
                    audit=audit,
                    receipt_store=receipt_store,
                    mni_client_factory=mni_client_factory,
                    mni_auth=mni_auth,
                )
                result = asyncio.run(orchestrator.file(filing_request))
    except Exception as exc:
        console.print(f"[red]Erro fatal: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    # 8. Display results
    if result.preflight:
        pf = result.preflight
        status_style = {
            "safe": "green",
            "urgent": "yellow",
            "expiring": "red",
            "expired": "bold red",
            "unknown": "dim",
        }
        style = status_style.get(pf.prazo_status.value, "dim")
        console.print(f"\n[bold]Pre-flight:[/bold] {'PASSED' if pf.passed else 'BLOCKED'}")
        console.print(f"  Prazo: [{style}]{pf.prazo_status.value.upper()}[/{style}]")
        for check in pf.checks:
            icon = "[green]✓[/green]" if check.passed else "[red]✗[/red]"
            console.print(f"  {icon} {check.name}: {check.message}")

    if dry_run:
        console.print("\n[bold yellow]DRY-RUN:[/bold yellow] Nenhuma assinatura ou protocolo realizado.")
        console.print(f"  Processo: {numero_cnj}")
        console.print(f"  Tribunal: {tribunal}")
        console.print(f"  Tipo: {tipo_doc}")
        if result.preflight:
            console.print(f"  Prazo: {result.preflight.prazo_status.value}")
        return

    if result.success:
        console.print(f"\n[bold green]Petição protocolada com sucesso![/bold green]")
        if result.receipt:
            console.print(f"  Protocolo: [bold]{result.receipt.protocolo}[/bold]")
            console.print(f"  Mensagem: {result.receipt.mensagem}")
        if result.signing_result:
            console.print(f"  Assinante: {result.signing_result.signer_name}")
            console.print(f"  CPF: {result.signing_result.signer_cpf}")
        if result.chain_of_custody:
            console.print(f"  [dim]PDF hash: {result.chain_of_custody.pdf_hash[:16]}...[/dim]")
            console.print(f"  [dim]Signed hash: {result.chain_of_custody.signed_pdf_hash[:16]}...[/dim]")
        console.print(f"  Audit entries: {len(result.audit_entry_ids)}")
    else:
        console.print(f"\n[bold red]Falha no protocolo.[/bold red]")
        console.print(f"  Erro: {result.error}")
        if result.audit_entry_ids:
            console.print(f"  [dim]Audit entries: {len(result.audit_entry_ids)}[/dim]")
        raise typer.Exit(code=1)


from juris.cli.search_cli import search_app

app.add_typer(search_app, name="search")


if __name__ == "__main__":
    app()
