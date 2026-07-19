"""``juris tenant`` — onboard a firm to the multi-tenant SaaS (hashed API keys)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

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


@tenant_app.command("promote")
def promote_tenant(
    tenant_id: str = typer.Argument(..., help="Identificador do teste anônimo a promover (pagamento confirmado)."),
) -> None:
    """Promote a paid trial to a permanent account (post-payment activation).

    Keeps keys, data and optional contact e-mail; removes the trial expiry so
    the automatic purge never touches the tenant. Run after confirming the
    R$ 200/month payment; a billing webhook can call the same function later.
    """
    from juris.web.trial_access import promote_trial_to_account

    try:
        entry = promote_trial_to_account(tenant_id)
    except KeyError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None
    except ValueError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=1) from None

    contact = entry.get("contact_email") or "—"
    console.print(f"[green]Tenant '{tenant_id}' promovido a conta permanente.[/green]")
    console.print(f"  contato: {contact} · promovido em: {entry.get('promoted_at')}")
    console.print("  A chave existente continua válida; o purge automático não toca mais este tenant.")


@tenant_app.command("alert-emails")
def alert_emails_cmd(
    tenant_id: str = typer.Argument(..., help="Tenant cujos destinatários de alerta de prazo serão geridos."),
    add: str | None = typer.Option(None, "--add", help="Adiciona um e-mail à lista de destinatários."),
    remove: str | None = typer.Option(None, "--remove", help="Remove um e-mail da lista de destinatários."),
    list_recipients: bool = typer.Option(
        False,
        "--list",
        help=(
            "Lista os destinatários atuais. Implícito quando --add/--remove não são usados; "
            "combine com --add/--remove para também imprimir a lista completa após a mutação."
        ),
    ),
) -> None:
    """Manage a tenant's deadline-alert e-mail recipients (tenants.json).

    A legacy string entry (bare API-key hash) is migrated to the structured
    format on ``--add``/``--remove``, preserving the existing key hash so
    already-issued API keys keep authenticating.
    """
    from juris.web.trial_access import add_alert_email, alert_emails_for_tenant, remove_alert_email

    mutated = add is not None or remove is not None
    try:
        if add:
            emails = add_alert_email(tenant_id, add)
            console.print(f"[green]Adicionado.[/green] Destinatários de '{tenant_id}': {len(emails)}")
        elif remove:
            emails = remove_alert_email(tenant_id, remove)
            console.print(f"[green]Removido.[/green] Destinatários de '{tenant_id}': {len(emails)}")
        else:
            emails = alert_emails_for_tenant(tenant_id)
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

    # After a mutation, the terse confirmation above is enough unless --list was
    # explicitly asked for; a bare (read-only) invocation always lists.
    if mutated and not list_recipients:
        return
    if not emails:
        console.print(f"[yellow]Nenhum destinatário configurado para '{tenant_id}'.[/yellow]")
        return
    for email in emails:
        console.print(f"  {email}")


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
    revoked = "sim" if result.access_revoked else "não (tenants.json ausente ou já sem entrada)"
    console.print(f"  Acesso (chave) revogado: {revoked}")
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


@tenant_app.command("purge-expired")
def purge_expired(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Prevê a varredura e o que seria apagado; não muda nada em disco (nem tenants.json nem o ledger).",
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Pula a confirmação interativa (uso não-interativo, ex.: launchd/cron)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emite JSON para automação/runbook."),
) -> None:
    """Apaga dados de trials expirados e emite o certificado de erasure de cada um.

    Fonte da verdade: o ledger ``pending-erasure.json`` ao lado de
    ``JURIS_TENANTS_FILE``, populado quando um trial expirado é removido de
    tenants.json (a perda de ACESSO já acontece ali; este comando fecha o ciclo
    apagando os DADOS). Também varre tenants.json por trials ainda
    expirados-mas-presentes antes de processar (prune + enqueue + erase no mesmo
    run); ``--dry-run`` prevê essa varredura em memória, sem nenhuma escrita.

    Nunca apaga um tenant_id presente e não-expirado em tenants.json; um id
    assim no ledger é leftover (crash entre ledger e pop, ou edição manual) e é
    removido do ledger sem apagar nada. JSON ilegível em qualquer arquivo →
    fail-closed: nada é apagado, ids continuam pendentes, exit não-zero.
    """
    from contextlib import nullcontext

    from juris.web.trial_access import acquire_purge_lock, tenants_file_path

    now = datetime.now(UTC)
    tenants_path = tenants_file_path()

    lock_ctx = nullcontext(True) if dry_run else acquire_purge_lock(tenants_path)
    with lock_ctx as acquired:
        if not acquired:
            _abort_purge(json_output, dry_run, "outra execução de purge-expired em andamento (lock ocupado)")
        _run_purge(tenants_path, now=now, dry_run=dry_run, yes=yes, json_output=json_output)


def _abort_purge(json_output: bool, dry_run: bool, error: str) -> NoReturn:
    """Fail closed: report a clean error (visible in --json) and exit non-zero."""
    _print_purge_summary(
        json_output,
        swept=[],
        erased=[],
        stale=[],
        failed=[],
        errors=[{"error": f"{error}; nada foi apagado."}],
        dry_run=dry_run,
    )
    raise typer.Exit(code=1)


def _run_purge(tenants_path: Path, *, now: datetime, dry_run: bool, yes: bool, json_output: bool) -> None:
    from juris.ops.erasure import append_stale_drop_event, build_tenant_erasure_plan, execute_tenant_erasure
    from juris.web.trial_access import (
        agents_file_path,
        is_tenant_active,
        preview_expired_trials,
        read_pending_erasure,
        remove_from_pending_erasure,
        sweep_expired_trials,
    )

    try:
        if dry_run:
            # In-memory preview of the sweep: expired-but-still-listed trials are
            # shown exactly as the next real run would treat them, with zero writes.
            swept = sorted(preview_expired_trials(tenants_path, now=now))
            pending = read_pending_erasure(tenants_path)
            for tenant_id in swept:
                pending.setdefault(tenant_id, {"preview": True})
        else:
            swept = sorted(sweep_expired_trials(tenants_path=tenants_path, agents_path=agents_file_path(), now=now))
            pending = read_pending_erasure(tenants_path)
    except (ValueError, OSError) as exc:  # includes json.JSONDecodeError
        _abort_purge(json_output, dry_run, f"estado ilegível (fail-closed): {exc}")

    if not pending:
        _print_purge_summary(json_output, swept=swept, erased=[], stale=[], failed=[], errors=[], dry_run=dry_run)
        raise typer.Exit(code=0)

    if not dry_run and not yes and not typer.confirm(
        f"Apagar dados de {len(pending)} tenant(s) de trial expirado(s)?", default=False
    ):
        console.print("[yellow]Cancelado.[/yellow]")
        raise typer.Exit(code=1)

    erased: list[dict[str, object]] = []
    stale: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []

    for tenant_id in sorted(pending):
        try:
            active = is_tenant_active(tenants_path, tenant_id, now=now)
        except (ValueError, OSError) as exc:
            failed.append({"tenant_id": tenant_id, "error": f"tenants.json ilegível (fail-closed): {exc}"})
            continue
        if active:
            # Ledger leftover: crash between ledger-write and pop, or a hand-edit.
            # Active + non-expired must never be erased — drop the stale entry.
            # Dropping discards an LGPD erasure obligation, so persist the event
            # to the compliance trail BEFORE clearing the ledger (crash between
            # the two just re-drops on the next run, appending a duplicate event).
            reason = "ativo e não-expirado no tenants.json (leftover de crash ou reuso de id)"
            if not dry_run:
                try:
                    append_stale_drop_event(tenant_id, reason=reason)
                    remove_from_pending_erasure(tenants_path, tenant_id)
                except OSError as exc:
                    failed.append({"tenant_id": tenant_id, "error": f"falha ao registrar stale-drop: {exc}"})
                    continue
            stale.append({"tenant_id": tenant_id, "reason": f"{reason}; removido do ledger, nada apagado"})
            continue
        try:
            plan = build_tenant_erasure_plan(tenant_id)
        except ValueError as exc:
            failed.append({"tenant_id": tenant_id, "error": str(exc)})
            continue
        if dry_run:
            erased.append({"tenant_id": tenant_id, "dry_run": True, "plan": plan.to_dict()})
            continue
        try:
            result = execute_tenant_erasure(plan, confirmation=plan.confirmation_phrase)
        except Exception as exc:  # noqa: BLE001 -- one tenant's I/O failure must not abort the batch;
            # the id simply stays in the ledger for the next scheduled run to retry.
            failed.append({"tenant_id": tenant_id, "error": str(exc)})
            continue
        remove_from_pending_erasure(tenants_path, tenant_id)
        erased.append({"tenant_id": tenant_id, "result": result.to_dict()})

    _print_purge_summary(
        json_output, swept=swept, erased=erased, stale=stale, failed=failed, errors=[], dry_run=dry_run
    )
    raise typer.Exit(code=1 if failed else 0)


def _print_purge_summary(
    json_output: bool,
    *,
    swept: list[str],
    erased: list[dict[str, object]],
    stale: list[dict[str, object]],
    failed: list[dict[str, object]],
    errors: list[dict[str, object]],
    dry_run: bool,
) -> None:
    if json_output:
        console.print_json(
            json.dumps(
                {
                    "dry_run": dry_run,
                    "swept": swept,
                    "erased": erased,
                    "stale": stale,
                    "failed": failed,
                    "errors": errors,
                },
                ensure_ascii=False,
            )
        )
        return
    if not erased and not stale and not failed and not errors:
        console.print("[green]Nada pendente de erasure.[/green]")
        return
    console.print(f"[bold]Purge de trials expirados[/bold]{' (dry-run)' if dry_run else ''}:")
    if swept:
        label = "Seriam varridos de tenants.json (expirados)" if dry_run else "Varridos de tenants.json (expirados)"
        console.print(f"  {label}: {', '.join(swept)}")
    for item in erased:
        verb = "seria apagado" if dry_run else "OK"
        console.print(f"  [green]{verb}[/green] {item['tenant_id']}")
    for item in stale:
        console.print(f"  [yellow]obsoleto[/yellow] {item['tenant_id']}: {item['reason']}")
    for item in failed:
        console.print(f"  [red]falhou[/red] {item['tenant_id']}: {item['error']}")
    for item in errors:
        console.print(f"  [red]erro[/red] {item['error']}")
