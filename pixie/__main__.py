"""Command-line entry point for Pixie.

Exposes the ``pixie`` console script. The CLI is the contributor's main
surface and stays short, mnemonic and lazy. Subcommands:

* ``pixie`` / ``pixie serve`` — boots the FastAPI host via uvicorn on
  ``127.0.0.1`` (loopback only, never binds a public interface).
* ``pixie dev`` — like ``serve`` but with hot-reload, debug logging,
  dev-mode env, hover prewarm.
* ``pixie validate <tool_id>`` — run the full eleven-check validator.
  ``--summary`` returns only failed/warning checks (token-efficient).
  ``--export-check`` exports each output to its default format.
* ``pixie tail <tool_id>`` — follow a tool's stderr ring buffer (or
  recent artefacts with ``--artefacts``).
* ``pixie open <tool_id>`` — open the tool folder in the OS file browser.
* ``pixie sweep`` — run the retention sweeper on demand.
* ``pixie artefacts <tool_id>`` — list a tool's artefacts.
* ``pixie scaffold-tool <tool_id>`` — render a starter tool from a
  template under ``pixie/templates_scaffold/<name>/``.

Uvicorn is invoked programmatically against the ``create_app`` factory
so test code and CLI share one code path.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import typer
import uvicorn
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from pixie.cli_helpers import (
    ScaffoldError,
    TEMPLATES_ROOT,
    list_templates,
    open_in_os,
    scaffold,
)
from pixie.config import get_settings
from pixie.validator import (
    summary_report,
    update_reference_fixtures_sync,
    validate_tool_sync,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Pixie — a local-first dashboard for your personal tools and models.",
)


_STATUS_STYLE = {
    "pass": "green",
    "fail": "red",
    "warn": "yellow",
    "skip": "dim",
}


# --- shared helpers ---------------------------------------------------------


def _stderr_console() -> Console:
    return Console(stderr=True)


def _resolve_tools_dir(tools_dir: Path | None) -> Path:
    return tools_dir if tools_dir is not None else get_settings().tools_dir


def _require_tool_path(tool_id: str, tools_dir: Path | None) -> Path:
    resolved = _resolve_tools_dir(tools_dir)
    candidate = (resolved / tool_id).resolve()
    if not candidate.is_dir():
        typer.echo(f"error: tool folder not found at {candidate}", err=True)
        raise typer.Exit(code=2)
    return candidate


# --- serve / dev ------------------------------------------------------------


@app.command()
def serve(
    port: int = typer.Option(
        None,
        "--port",
        "-p",
        help="TCP port to bind on 127.0.0.1. Defaults to PIXIE_PORT env or 7860.",
    ),
) -> None:
    """Run the Pixie web host on the loopback interface."""

    resolved_port = port if port is not None else int(os.environ.get("PIXIE_PORT", "7860"))
    config = uvicorn.Config(
        app="pixie.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=resolved_port,
        log_level="info",
        access_log=False,
        loop="auto",
        http="h11",
        ws="none",
        workers=1,
    )
    server = uvicorn.Server(config)
    server.run()


@app.command()
def dev(
    port: int = typer.Option(
        None,
        "--port",
        "-p",
        help="TCP port to bind on 127.0.0.1. Defaults to PIXIE_PORT env or 7860.",
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Skip opening the dashboard in the default browser.",
    ),
) -> None:
    """Run Pixie in developer mode: hot-reload, debug logging, dev env set."""

    resolved_port = port if port is not None else int(os.environ.get("PIXIE_PORT", "7860"))

    os.environ["PIXIE_DEV_MODE"] = "true"
    os.environ["PIXIE_DEVELOPER_MODE"] = "true"
    os.environ["PIXIE_LOG_LEVEL"] = "DEBUG"
    os.environ["PIXIE_HOVER_PREWARM"] = "true"
    os.environ["PIXIE_WATCH"] = "true"

    console = _stderr_console()
    console.rule("[bold magenta]Pixie dev mode")
    console.print(
        "[dim]hot-reload watching[/dim] [cyan]pixie/[/cyan], "
        "[cyan]tools/[/cyan]  [dim]·[/dim]  log-level [yellow]DEBUG[/yellow]  "
        "[dim]·[/dim]  hover-prewarm [green]on[/green]"
    )

    if not no_browser:
        url = f"http://127.0.0.1:{resolved_port}"
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    # uvicorn's --reload uses watchfiles internally; declaring reload_dirs
    # explicitly keeps changes under tools/ from being missed.
    uvicorn.run(
        "pixie.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=resolved_port,
        log_level="debug",
        access_log=False,
        reload=True,
        reload_dirs=["pixie", "tools"],
        loop="auto",
        http="h11",
        ws="none",
        workers=1,
    )


# --- validate ---------------------------------------------------------------


def _print_human_report(report_dict: dict) -> None:
    """Render the validation report as a rich-formatted summary on stderr."""

    console = _stderr_console()
    overall = report_dict.get("overall", "?")
    overall_style = _STATUS_STYLE.get(overall, "white")
    console.print(
        f"\n[bold]Validation report[/bold] for "
        f"[cyan]{report_dict.get('tool_id')}[/cyan] — "
        f"overall: [{overall_style}]{overall.upper()}[/{overall_style}]"
    )
    console.print(f"  path: {report_dict.get('tool_path')}")
    console.print(f"  timestamp: {report_dict.get('timestamp')}\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", width=2)
    table.add_column("Check")
    table.add_column("Status", width=6)
    table.add_column("Message")
    for index, check in enumerate(report_dict.get("checks", []), start=1):
        status = check.get("status", "?")
        style = _STATUS_STYLE.get(status, "white")
        table.add_row(
            str(index),
            check.get("name", ""),
            f"[{style}]{status}[/{style}]",
            check.get("message", ""),
        )
    console.print(table)

    for check in report_dict.get("checks", []):
        details = check.get("details")
        if details:
            console.print(f"\n[dim]Details for {check.get('name')}:[/dim]")
            console.print(details, highlight=False)
    if report_dict.get("spawn_log"):
        console.print("\n[dim]Captured stderr:[/dim]")
        console.print(report_dict["spawn_log"], highlight=False)


def _print_summary(report_dict: dict) -> None:
    console = _stderr_console()
    summary = summary_report(report_dict)
    overall = summary.get("overall", "?")
    overall_style = _STATUS_STYLE.get(overall, "white")
    counts = summary.get("counts", {})
    console.print(
        f"[bold]{summary.get('tool_id')}[/bold] — "
        f"overall: [{overall_style}]{overall.upper()}[/{overall_style}]  "
        f"[dim]pass={counts.get('pass', 0)} "
        f"warn={counts.get('warn', 0)} "
        f"fail={counts.get('fail', 0)} "
        f"skip={counts.get('skip', 0)}[/dim]"
    )
    notable = summary.get("notable_checks", [])
    if not notable:
        console.print("[green]all checks pass; nothing notable.[/green]")
        return
    for check in notable:
        style = _STATUS_STYLE.get(check.get("status"), "white")
        console.print(
            f"  [{style}]{check.get('status')}[/{style}] "
            f"[bold]{check.get('name')}[/bold]: {check.get('message')}"
        )
        if check.get("details"):
            console.print(f"    [dim]{check['details']}[/dim]", highlight=False)


@app.command()
def validate(
    tool_id: str = typer.Argument(..., help="Tool folder name (the directory under tools/)."),
    tools_dir: Path = typer.Option(
        None,
        "--tools-dir",
        help="Override the tools directory. Defaults to PIXIE_TOOLS_DIR or <repo>/tools.",
    ),
    json_only: bool = typer.Option(
        False, "--json", help="Print only the JSON report (skill-friendly).",
    ),
    no_save: bool = typer.Option(
        False, "--no-save", help="Do not persist the report to pixie.db.",
    ),
    summary: bool = typer.Option(
        False, "--summary",
        help="Token-efficient mode: emit only failed/warning checks plus counts.",
    ),
    export_check: bool = typer.Option(
        False, "--export-check",
        help="Also exercise the export dispatcher for each declared output.",
    ),
    reference_only: bool = typer.Option(
        False, "--reference-only",
        help=(
            "Skip the sample-run, output-conformance and streaming checks; "
            "run only the reference-fixtures accuracy check."
        ),
    ),
    fixture: list[str] = typer.Option(
        None, "--fixture",
        help=(
            "Run only the named fixture(s). Repeatable. Matches "
            "`fixture_<name>.json` exactly or by glob."
        ),
    ),
    tag: list[str] = typer.Option(
        None, "--tag",
        help="Run only fixtures whose tags array contains <tag>. Repeatable.",
    ),
    update_fixtures: bool = typer.Option(
        False, "--update-fixtures",
        help=(
            "Re-run each fixture and overwrite its expected_outputs. "
            "Dangerous — requires --yes to commit."
        ),
    ),
    yes: bool = typer.Option(
        False, "--yes",
        help="Confirm a destructive operation (currently: --update-fixtures).",
    ),
) -> None:
    """Validate a tool end-to-end and print its report."""

    tool_path = _require_tool_path(tool_id, tools_dir)

    if update_fixtures:
        report = update_reference_fixtures_sync(
            tool_path,
            fixture_filter=fixture or None,
            dry_run=not yes,
        )
        console = _stderr_console()
        if report.get("errors"):
            console.print("[red]Errors:[/red]")
            for err in report["errors"]:
                console.print(f"  {err}")
        for entry in report.get("skipped", []):
            console.print(
                f"[dim]skip[/dim] {entry['file']} ({entry['reason']})"
            )
        if not yes:
            would = report.get("would_update", [])
            console.print(
                f"[yellow]Dry run:[/yellow] would update {len(would)} fixture(s)."
            )
            for entry in would:
                console.print(
                    f"  {entry['file']} (changed keys: {entry['delta_keys']})"
                )
            console.print(
                "Pass [bold]--yes[/bold] to commit the rewrite."
            )
        else:
            console.print(
                f"[green]Updated {len(report.get('updated', []))} fixture(s).[/green]"
            )
            for name in report["updated"]:
                console.print(f"  {name}")
        typer.echo(json.dumps(report, indent=2, default=str))
        raise typer.Exit(code=1 if report.get("errors") else 0)

    report = validate_tool_sync(
        tool_path,
        save_to_db=not no_save,
        reference_only=reference_only,
        fixture_filter=fixture or None,
        tag_filter=tag or None,
    )
    report_payload = json.loads(report.model_dump_json())

    if summary:
        summary_payload = summary_report(report_payload)
        if not json_only:
            _print_summary(report_payload)
        typer.echo(json.dumps(summary_payload, indent=2, default=str))
    else:
        if not json_only:
            _print_human_report(report_payload)
        typer.echo(json.dumps(report_payload, indent=2, default=str))

    if export_check:
        # The export dispatcher is owned by the polish-pass agent (Wave 2);
        # surface a clear hint rather than silently passing.
        _stderr_console().print(
            "\n[yellow]--export-check[/yellow]: export dispatcher not yet wired; "
            "the polish-pass agent (Wave 2) replaces this hint with the real "
            "round-trip exercise once pixie/exporters/ lands."
        )

    raise typer.Exit(code=1 if report.overall == "fail" else 0)


# --- tail -------------------------------------------------------------------


@app.command()
def tail(
    tool_id: str = typer.Argument(..., help="Tool folder name."),
    tools_dir: Path = typer.Option(
        None, "--tools-dir", help="Override the tools directory.",
    ),
    artefacts: bool = typer.Option(
        False, "--artefacts", help="List recent artefacts instead of stderr.",
    ),
    lines: int = typer.Option(
        50, "--lines", "-n", help="Max lines (or artefacts) to show.",
    ),
    port: int = typer.Option(
        None, "--port", "-p", help="Pixie port (default PIXIE_PORT or 7860).",
    ),
) -> None:
    """Follow a tool's stderr ring buffer or list its recent artefacts."""

    _require_tool_path(tool_id, tools_dir)
    console = _stderr_console()

    if artefacts:
        asyncio.run(_tail_artefacts(tool_id, lines, console))
        return

    resolved_port = port if port is not None else int(os.environ.get("PIXIE_PORT", "7860"))
    base_url = f"http://127.0.0.1:{resolved_port}"
    asyncio.run(_tail_stderr(base_url, tool_id, lines, console))


async def _tail_artefacts(tool_id: str, limit: int, console: Console) -> None:
    settings = get_settings()
    rows = await _recent_artefact_rows(settings.db_path, tool_id, limit)
    if not rows:
        console.print(
            f"[dim]no recent artefacts for {tool_id} "
            "(the artefact subsystem lands with Wave 2)."
        )
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Created")
    table.add_column("Output key")
    table.add_column("Filename")
    table.add_column("Size", justify="right")
    table.add_column("Path", overflow="fold")
    for row in rows:
        table.add_row(
            str(row.get("created_at", "")),
            row.get("output_key", ""),
            row.get("filename", ""),
            _format_bytes(row.get("size_bytes", 0)),
            row.get("rel_path", ""),
        )
    console.print(table)


async def _recent_artefact_rows(
    db_path: Path, tool_id: str, limit: int
) -> list[dict[str, object]]:
    """Best-effort lookup against the (future) artefacts table.

    The artefacts table is provisioned by the polish-pass agent; until
    then, this function returns ``[]`` rather than crashing. That keeps
    ``pixie tail --artefacts`` usable today and means no rewrite when
    Wave 2 lands.
    """

    import sqlite3

    from pixie import db as _db

    def _query() -> list[dict[str, object]]:
        try:
            conn = _db.connect(db_path)
            try:
                cur = conn.execute(
                    "SELECT created_at, output_key, filename, size_bytes, rel_path "
                    "FROM artefacts WHERE tool_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (tool_id, limit),
                )
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()
        except sqlite3.OperationalError:
            return []

    return await asyncio.to_thread(_query)


def _format_bytes(size: object) -> str:
    try:
        n = float(size or 0)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


async def _tail_stderr(
    base_url: str, tool_id: str, lines: int, console: Console
) -> None:
    """Pull the stderr ring buffer via the Pixie API."""

    url = f"{base_url}/api/tools/{tool_id}/logs"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            response = await client.get(url, params={"limit": lines})
    except httpx.HTTPError as exc:
        console.print(
            f"[red]could not reach Pixie at {base_url}:[/red] {exc}\n"
            "[dim]is `pixie serve` running?[/dim]"
        )
        raise typer.Exit(code=1)

    if response.status_code == 404:
        console.print(
            f"[yellow]{tool_id} is not currently warm.[/yellow] "
            "[dim]Open it in the dashboard first.[/dim]"
        )
        raise typer.Exit(code=1)
    if response.status_code != 200:
        console.print(
            f"[red]GET /api/tools/{tool_id}/logs returned "
            f"HTTP {response.status_code}[/red]\n{response.text[:500]}"
        )
        raise typer.Exit(code=1)

    try:
        body = response.json()
    except json.JSONDecodeError:
        sys.stdout.write(response.text)
        sys.stdout.flush()
        return

    log_lines = body.get("lines") if isinstance(body, dict) else None
    if isinstance(log_lines, list):
        for line in log_lines[-lines:]:
            sys.stdout.write(str(line))
            if not str(line).endswith("\n"):
                sys.stdout.write("\n")
        sys.stdout.flush()
    else:
        sys.stdout.write(json.dumps(body, indent=2))
        sys.stdout.write("\n")


# --- open -------------------------------------------------------------------


@app.command()
def open(  # noqa: A001 — typer command name, not the built-in
    tool_id: str = typer.Argument(..., help="Tool folder name."),
    tools_dir: Path = typer.Option(
        None, "--tools-dir", help="Override the tools directory.",
    ),
) -> None:
    """Open a tool's folder in the host file browser."""

    tool_path = _require_tool_path(tool_id, tools_dir)
    try:
        open_in_os(tool_path)
    except OSError as exc:
        typer.echo(f"error: could not open {tool_path}: {exc}", err=True)
        raise typer.Exit(code=1)
    _stderr_console().print(f"[green]opened[/green] {tool_path}")


# --- sweep ------------------------------------------------------------------


_DURATION_UNITS = {
    "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800,
}


def _parse_duration(spec: str) -> timedelta:
    spec = spec.strip().lower()
    if not spec:
        raise typer.BadParameter("empty duration")
    unit = spec[-1]
    if unit not in _DURATION_UNITS:
        # treat as plain seconds
        try:
            return timedelta(seconds=int(spec))
        except ValueError as exc:
            raise typer.BadParameter(f"could not parse duration {spec!r}") from exc
    try:
        amount = int(spec[:-1])
    except ValueError as exc:
        raise typer.BadParameter(f"could not parse duration {spec!r}") from exc
    return timedelta(seconds=amount * _DURATION_UNITS[unit])


@app.command()
def sweep(
    dry_run: bool = typer.Option(
        True, "--dry-run/--apply",
        help="Default is dry-run; pass --apply to actually delete.",
    ),
    older_than: str = typer.Option(
        "30d", "--older-than",
        help="Cutoff age, e.g. 7d, 24h, 30m. Runs older than this become candidates.",
    ),
    tool: str = typer.Option(
        None, "--tool", help="Limit the sweep to one tool id.",
    ),
) -> None:
    """Run the retention sweeper on demand.

    Walks ``runs`` (and, once Wave 2 lands, ``artefacts``) and reports
    rows older than ``--older-than`` that aren't starred or labelled.
    """

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - _parse_duration(older_than)
    console = _stderr_console()
    console.print(
        f"[bold]sweep[/bold] cutoff = [cyan]{cutoff.isoformat()}[/cyan]  "
        f"({'dry-run' if dry_run else 'APPLY'})"
    )

    candidates = _sweep_candidates(settings.db_path, cutoff, tool_filter=tool)
    if not candidates:
        console.print("[green]nothing to prune.[/green]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Tool")
    table.add_column("Run id", overflow="fold")
    table.add_column("Started")
    table.add_column("Status", width=8)
    for row in candidates:
        table.add_row(
            row.get("tool_id", ""),
            row.get("id", ""),
            str(row.get("started_at", "")),
            row.get("status", ""),
        )
    console.print(table)
    console.print(f"[dim]{len(candidates)} candidate run(s).[/dim]")

    if dry_run:
        console.print(
            "[yellow]dry-run; nothing deleted.[/yellow] "
            "Pass [bold]--apply[/bold] to actually prune."
        )
        return

    deleted = _sweep_apply(settings.db_path, [row["id"] for row in candidates])
    console.print(f"[green]pruned {deleted} run(s).[/green]")
    console.print(
        "[dim]artefact files on disk are owned by the artefact subsystem "
        "(Wave 2). When that lands, sweep also removes the artefact files "
        "referenced by these run rows.[/dim]"
    )

    # Reconcile orphaned archived flags (4.1).
    cleared = _sweep_reconcile_archived(settings)
    if cleared:
        console.print(
            f"[yellow]sweep: cleared {cleared} orphaned "
            f"archived flag(s).[/yellow]"
        )


def _sweep_reconcile_archived(settings) -> int:
    """For every tool_state row with archived=1, if the tool folder exists
    on disk AND there is no archive_log row, clear the archived flag.

    Returns the number of rows cleared.
    """

    import logging
    import sqlite3

    logger = logging.getLogger("pixie")
    db_path = settings.db_path
    tools_dir = settings.tools_dir

    cleared = 0
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT tool_id FROM tool_state WHERE archived = 1"
            ).fetchall()
            for row in rows:
                tool_id = row["tool_id"]
                tool_path = tools_dir / tool_id
                if not tool_path.is_dir():
                    # Tool genuinely gone; leave archived=1 alone (it's a
                    # tombstone for a missing tool).
                    continue
                logged = conn.execute(
                    "SELECT 1 FROM archive_log WHERE tool_id = ? LIMIT 1",
                    (tool_id,),
                ).fetchone()
                if logged:
                    continue
                conn.execute(
                    "UPDATE tool_state SET archived = 0, archived_at = NULL "
                    "WHERE tool_id = ?",
                    (tool_id,),
                )
                logger.info(
                    "sweep: cleared orphaned archived flag for %s", tool_id
                )
                cleared += 1
            conn.commit()
    except sqlite3.OperationalError:
        # archive_log table may not exist on a brand-new DB before init_db
        # has been called; treat as nothing-to-do.
        return 0
    return cleared


@app.command()
def archive(
    tool_id: str = typer.Argument(..., help="Tool folder name."),
) -> None:
    """Archive a tool — hides it from the sidebar and records the action."""

    settings = get_settings()
    tool_path = settings.tools_dir / tool_id
    if not tool_path.is_dir():
        _stderr_console().print(
            f"[red]no such tool:[/red] {tool_id}"
        )
        raise typer.Exit(code=1)
    asyncio.run(_archive_async(settings.db_path, tool_id))
    _stderr_console().print(f"[green]archived[/green] {tool_id}")


async def _archive_async(db_path: Path, tool_id: str) -> None:
    from pixie import db
    await db.set_archived(db_path, tool_id, True)
    await db.log_archive(db_path, tool_id, source="cli")


@app.command()
def unarchive(
    tool_id: str = typer.Argument(..., help="Tool folder name."),
) -> None:
    """Unarchive a tool — restores it to the sidebar."""

    settings = get_settings()
    asyncio.run(_unarchive_async(settings.db_path, tool_id))
    _stderr_console().print(f"[green]unarchived[/green] {tool_id}")


async def _unarchive_async(db_path: Path, tool_id: str) -> None:
    from pixie import db
    await db.set_archived(db_path, tool_id, False)
    await db.unlog_archive(db_path, tool_id)


def _sweep_candidates(
    db_path: Path, cutoff: datetime, tool_filter: str | None
) -> list[dict[str, object]]:
    import sqlite3

    sql = (
        "SELECT id, tool_id, started_at, status, "
        "COALESCE(starred, 0) AS starred, COALESCE(label, '') AS label "
        "FROM runs WHERE started_at < ? "
    )
    params: list[object] = [cutoff.isoformat()]
    if tool_filter:
        sql += "AND tool_id = ? "
        params.append(tool_filter)
    sql += "ORDER BY started_at ASC"

    from pixie import db as _db
    try:
        conn = _db.connect(db_path)
        try:
            cur = conn.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        # Tolerant: the runs table might be missing the starred/label
        # columns until the artefact migration lands.
        if "no such column" in str(exc):
            base_sql = (
                "SELECT id, tool_id, started_at, status FROM runs "
                "WHERE started_at < ?"
            )
            base_params: list[object] = [cutoff.isoformat()]
            if tool_filter:
                base_sql += " AND tool_id = ?"
                base_params.append(tool_filter)
            base_sql += " ORDER BY started_at ASC"
            conn = _db.connect(db_path)
            try:
                cur = conn.execute(base_sql, base_params)
                rows = [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()
        else:
            raise
    # Drop starred / labelled (never prune them).
    return [
        row for row in rows
        if not row.get("starred") and not (row.get("label") or "").strip()
    ]


def _sweep_apply(db_path: Path, run_ids: list[str]) -> int:
    from pixie import db as _db

    if not run_ids:
        return 0
    placeholders = ",".join("?" for _ in run_ids)
    conn = _db.connect(db_path)
    try:
        cur = conn.execute(
            f"DELETE FROM runs WHERE id IN ({placeholders})", run_ids,
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


# --- artefacts --------------------------------------------------------------


@app.command()
def artefacts(
    tool_id: str = typer.Argument(..., help="Tool folder name."),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows to list."),
    starred_only: bool = typer.Option(
        False, "--starred-only", help="Only show starred artefacts.",
    ),
) -> None:
    """List a tool's artefacts.

    Reads the ``artefacts`` table; if the table is absent (artefact
    subsystem lands with Wave 2), prints a calm hint instead of failing.
    """

    settings = get_settings()
    rows = asyncio.run(
        _recent_artefact_rows_filtered(settings.db_path, tool_id, limit, starred_only)
    )
    console = _stderr_console()
    if not rows:
        console.print(
            f"[dim]no artefacts for {tool_id} yet "
            "(the artefacts table is provisioned by the polish-pass agent).[/dim]"
        )
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("★", width=2)
    table.add_column("Created")
    table.add_column("Output")
    table.add_column("Filename")
    table.add_column("Size", justify="right")
    table.add_column("Path", overflow="fold")
    for row in rows:
        star = "*" if row.get("starred") else ""
        table.add_row(
            star,
            str(row.get("created_at", "")),
            row.get("output_key", ""),
            row.get("filename", ""),
            _format_bytes(row.get("size_bytes", 0)),
            row.get("rel_path", ""),
        )
    console.print(table)


async def _recent_artefact_rows_filtered(
    db_path: Path, tool_id: str, limit: int, starred_only: bool
) -> list[dict[str, object]]:
    import sqlite3

    sql = (
        "SELECT created_at, output_key, filename, size_bytes, rel_path, "
        "COALESCE(starred, 0) AS starred FROM artefacts "
        "WHERE tool_id = ? "
    )
    params: list[object] = [tool_id]
    if starred_only:
        sql += "AND starred = 1 "
    sql += "ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    from pixie import db as _db

    def _query() -> list[dict[str, object]]:
        try:
            conn = _db.connect(db_path)
            try:
                cur = conn.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()
        except sqlite3.OperationalError:
            return []

    return await asyncio.to_thread(_query)


# --- scaffold-tool ----------------------------------------------------------


@app.command("scaffold-tool")
def scaffold_tool(
    tool_id: str = typer.Argument(
        None,
        help="New tool folder name (lowercase, hyphenated). "
             "Required unless --template list is passed.",
    ),
    template: str = typer.Option(
        None, "--template", "-t",
        help="Template name (or 'list' to see all). Defaults to 'form' if omitted.",
    ),
    name: str = typer.Option(
        None, "--name", help="Human-readable display name (defaults to title-cased id).",
    ),
    description: str = typer.Option(
        None, "--description",
        help="One-line description used in tool.json and README.",
    ),
    tools_dir: Path = typer.Option(
        None, "--tools-dir", help="Override the tools directory.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing tool folder.",
    ),
    no_sync: bool = typer.Option(
        False, "--no-sync", help="Skip running `uv sync` in the new folder.",
    ),
    no_validate: bool = typer.Option(
        False, "--no-validate", help="Skip running the validator after scaffolding.",
    ),
) -> None:
    """Create a new tool folder from a built-in template."""

    console = _stderr_console()
    templates = list_templates()

    if template == "list":
        _render_template_list(console, templates)
        return

    if tool_id is None:
        if template is None:
            _render_template_list(console, templates)
            typer.echo(
                "\nerror: pass a tool id, e.g. "
                "`pixie scaffold-tool my-new-tool --template form`",
                err=True,
            )
            raise typer.Exit(code=2)
        typer.echo(
            "error: tool id is required (e.g. `pixie scaffold-tool my-new-tool`)",
            err=True,
        )
        raise typer.Exit(code=2)

    chosen_template = template
    if chosen_template is None:
        _render_template_list(console, templates)
        try:
            chosen_template = Prompt.ask(
                "\n[bold]template[/bold]",
                default="form",
                choices=[entry["name"] for entry in templates] or ["form"],
            )
        except (KeyboardInterrupt, EOFError):
            typer.echo("aborted.", err=True)
            raise typer.Exit(code=1)

    target_root = _resolve_tools_dir(tools_dir)
    target_root.mkdir(parents=True, exist_ok=True)

    console.print(
        f"[bold]scaffolding[/bold] [cyan]{tool_id}[/cyan] "
        f"from template [magenta]{chosen_template}[/magenta] "
        f"into [dim]{target_root}[/dim]"
    )

    try:
        destination = scaffold(
            tool_id=tool_id,
            template_name=chosen_template,
            target_root=target_root,
            name=name,
            description=description,
            force=force,
        )
    except ScaffoldError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1)

    console.print(f"  wrote [green]{destination}[/green]")

    if not no_sync:
        _run_uv_sync(destination, console)

    if not no_validate:
        _run_post_scaffold_validate(destination, console)

    console.print("\n[bold green]done.[/bold green]")
    console.print(
        f"  next: [cyan]pixie open {tool_id}[/cyan] · "
        f"[cyan]pixie validate {tool_id}[/cyan]"
    )


def _render_template_list(console: Console, templates: list[dict[str, str]]) -> None:
    if not templates:
        console.print(f"[red]no templates found under {TEMPLATES_ROOT}[/red]")
        return
    console.print("\n[bold]available templates[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Shape")
    table.add_column("Summary")
    for entry in templates:
        table.add_row(
            entry.get("name", ""),
            entry.get("shape", ""),
            entry.get("summary", ""),
        )
    console.print(table)


def _run_uv_sync(destination: Path, console: Console) -> None:
    console.print("  running [cyan]uv sync[/cyan] (may take a moment)…")
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["uv", "sync"],
            cwd=str(destination),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        console.print(
            "  [yellow]uv not found on PATH; skipping sync.[/yellow] "
            "[dim]install uv from https://docs.astral.sh/uv[/dim]"
        )
        return
    except subprocess.TimeoutExpired:
        console.print("  [red]uv sync timed out after 5 minutes.[/red]")
        return

    elapsed = time.monotonic() - start
    if result.returncode != 0:
        console.print(
            f"  [red]uv sync failed[/red] (exit {result.returncode}, {elapsed:.1f}s)"
        )
        tail_text = (result.stderr or result.stdout).strip().splitlines()[-20:]
        for line in tail_text:
            console.print(f"    [dim]{line}[/dim]", highlight=False)
        return
    console.print(f"  [green]uv sync ok[/green] ({elapsed:.1f}s)")


def _run_post_scaffold_validate(destination: Path, console: Console) -> None:
    console.print("  running [cyan]validator[/cyan]…")
    try:
        report = validate_tool_sync(destination, save_to_db=False)
    except Exception as exc:
        console.print(f"  [red]validator raised:[/red] {exc}")
        return
    style = _STATUS_STYLE.get(report.overall, "white")
    console.print(
        f"  validator: [{style}]{report.overall.upper()}[/{style}] "
        f"[dim]({len(report.checks)} check(s))[/dim]"
    )
    if report.overall != "pass":
        failed = [c for c in report.checks if c.status in ("fail", "warn")]
        for check in failed:
            sub_style = _STATUS_STYLE.get(check.status, "white")
            console.print(
                f"    [{sub_style}]{check.status}[/{sub_style}] "
                f"[bold]{check.name}[/bold]: {check.message}"
            )


# --- entry-point ------------------------------------------------------------


def main() -> None:
    """Console-script entry point declared in ``pyproject.toml``."""

    # Default to ``serve`` when no subcommand is given so ``pixie`` Just Works.
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    app()


if __name__ == "__main__":
    main()
