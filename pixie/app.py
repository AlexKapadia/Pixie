"""FastAPI application factory for the Pixie host.

The factory pattern (``create_app``) lets uvicorn build the app with
``factory=True`` and lets tests build a fresh app per test without
module-level singletons. Lifespan startup creates the shared httpx
client, the Launcher, initialises the SQLite schema, and starts the
idle sweeper. Shutdown reverses each step in order.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from contextlib import asynccontextmanager, suppress
from typing import Annotated, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pixie import db, secrets as pixie_secrets
from pixie import artefacts as artefacts_module
from pixie.artefacts import ArtefactRegistry
from pixie.config import Settings, get_settings
from pixie.discovery import discover_tools, discover_tools_parallel
from pixie.launcher import Launcher
from pixie.renderer.inputs import render_input, render_inputs
from pixie.renderer.outputs import render_output, render_outputs
from pixie.routes import (
    api,
    artefacts as artefacts_routes,
    dashboard,
    exports as exports_routes,
    library as library_routes,
    reference as reference_routes,
    settings as settings_routes,
    tool as tool_routes,
    tools_grid as tools_grid_routes,
    workspaces as workspaces_routes,
)
from pixie.validator import validate_tool

logger = logging.getLogger("pixie")


async def refresh_discovery(app: FastAPI) -> None:
    """Re-run parallel discovery and refresh ``app.state.discovered_tools``.

    Called once at startup; re-callable from the manual sidebar-refresh
    button and from a ``watchfiles`` callback when ``dev_mode`` is on.
    """

    settings: Settings = app.state.settings
    try:
        tools = await discover_tools_parallel(
            settings.tools_dir, concurrency=8
        )
    except Exception as exc:  # noqa: BLE001 — discovery is best-effort
        logger.warning("parallel discovery refresh failed: %s", exc)
        return
    app.state.discovered_tools = tools
    logger.info("discovered %d tools (parallel)", len(tools))


async def _periodic_disk_audit_refresh(app: FastAPI) -> None:
    """Every 24h: clear the disk-audit cache so the next request rebuilds it."""

    while True:
        await asyncio.sleep(24 * 3600)
        with suppress(Exception):
            app.state.disk_audit_cache = None
            logger.info("disk-audit cache invalidated (24h tick)")


async def _periodic_runs_prune(app: FastAPI) -> None:
    """Every 6h: prune old runs per-tool honouring each tool's retain_runs."""

    while True:
        await asyncio.sleep(6 * 3600)
        try:
            settings: Settings = app.state.settings
            tools = getattr(app.state, "discovered_tools", None)
            if not tools:
                tools = discover_tools(settings.tools_dir)
            for tool in tools:
                keep = tool.schema.retain_runs if tool.schema else 100
                with suppress(Exception):
                    await db.prune_starred_aware(
                        settings.db_path, tool.tool_id, keep=keep
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("periodic runs prune failed: %s", exc)


async def _validate_uncached_tools(settings: Settings) -> None:
    """Run the validator against every tool that has no cached report.

    Sequential rather than parallel: the validator spawns subprocesses,
    and we'd rather avoid five tools fighting for ports at boot.
    Failures here are logged, never raised; this is best-effort.
    """

    try:
        for tool in discover_tools(settings.tools_dir):
            if tool.schema is None:
                continue
            cached = await db.latest_validation_report(settings.db_path, tool.tool_id)
            if cached is not None:
                continue
            try:
                await validate_tool(tool.path, save_to_db=True)
            except Exception as exc:
                logger.warning(
                    "background validation failed for %s: %s", tool.tool_id, exc
                )
    except Exception as exc:
        logger.warning("startup validation sweep failed: %s", exc)


def _assert_loopback(host: str) -> None:
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError as exc:
        raise SystemExit(f"PIXIE_HOST must be an IP address, got {host!r}") from exc
    if not parsed.is_loopback:
        raise SystemExit(
            f"Pixie refuses to bind to {host!r}. Pixie is local-only. "
            "Edit your config or unset PIXIE_HOST."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import time as _time

    settings = get_settings()
    _assert_loopback(settings.host)
    app.state.settings = settings
    app.state.start_monotonic = _time.monotonic()
    app.state.start_unix = _time.time()
    app.state.revalidate_status = None

    db.init_db(settings.db_path)
    with suppress(Exception):
        await db.prune_old_reports(settings.db_path, days=30)

    # Install the secret-masking filter on the root logger and pre-load
    # every existing secret value so subsequent log records get scrubbed.
    pixie_secrets.install_masking_filter()
    with suppress(Exception):
        for tool in discover_tools(settings.tools_dir):
            declared = tool.schema.secrets if tool.schema else None
            pixie_secrets.SecretMaskingFilter.register_from_tool(
                tool.path, declared
            )

    # Apply persisted runtime-affecting settings before the launcher starts
    # so the very first warm-keep cycle uses the user's chosen values.
    with suppress(Exception):
        persisted_max = await db.get_setting(settings.db_path, "warm_keep_max")
        if persisted_max and persisted_max.isdigit():
            settings.warm_keep_max = int(persisted_max)
        persisted_keep = await db.get_setting(settings.db_path, "warm_keep_seconds")
        if persisted_keep and persisted_keep.isdigit():
            settings.warm_keep_seconds = int(persisted_keep)
        persisted_dev = await db.get_setting(settings.db_path, "developer_mode")
        if persisted_dev is not None:
            settings.developer_mode = persisted_dev in ("1", "true", "on")
        persisted_theme = await db.get_setting(settings.db_path, "theme")
        if persisted_theme in ("light", "dark"):
            settings.theme = persisted_theme  # type: ignore[assignment]
        persisted_accent = await db.get_setting(settings.db_path, "accent")
        if persisted_accent:
            settings.accent = persisted_accent
        persisted_density = await db.get_setting(settings.db_path, "density")
        if persisted_density in ("compact", "comfortable", "airy"):
            settings.density = persisted_density  # type: ignore[assignment]

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=2.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        follow_redirects=False,
    )
    launcher = Launcher(settings=settings, client=client)
    launcher.start_sweeper()

    # Local-first output persistence (RESEARCH_output_persistence). The
    # registry instantiates the artefacts root + reserved subdirs on first
    # construction; the sweeper task applies retention every 6h.
    artefacts_registry = ArtefactRegistry(settings)
    artefacts_sweeper = asyncio.create_task(
        artefacts_module.sweeper_loop(artefacts_registry),
        name="pixie-artefacts-sweeper",
    )

    app.state.client = client
    app.state.launcher = launcher
    app.state.artefacts = artefacts_registry
    app.state.artefacts_sweeper = artefacts_sweeper
    app.state.discovered_tools = []
    app.state.disk_audit_cache = None

    # Initial parallel discovery so the dashboard's first render hits cache.
    await refresh_discovery(app)

    # Restore each tool's pinned_warm state so the launcher's eviction
    # logic respects it from the very first spawn.
    with suppress(Exception):
        for tool in app.state.discovered_tools:
            state = await db.get_tool_state(settings.db_path, tool.tool_id)
            if state and state.get("pinned_warm"):
                launcher.set_pinned_warm(tool.tool_id, True)

    # Periodic sweepers (DECISIONS s30, RESEARCH_scale s5.2 + s7.3).
    app.state.disk_audit_task = asyncio.create_task(
        _periodic_disk_audit_refresh(app),
        name="pixie-disk-audit-refresh",
    )
    app.state.runs_prune_task = asyncio.create_task(
        _periodic_runs_prune(app),
        name="pixie-runs-prune",
    )

    # Kick off background validation for any tool that has no cached report.
    # This is fire-and-forget so startup is never blocked on tool spawns.
    asyncio.create_task(
        _validate_uncached_tools(settings), name="pixie-startup-validate"
    )

    logger.info("Pixie host starting on %s:%s", settings.host, settings.port)
    try:
        yield
    finally:
        logger.info("Pixie host shutting down")
        for task_attr in ("disk_audit_task", "runs_prune_task"):
            task = getattr(app.state, task_attr, None)
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if not artefacts_sweeper.done():
            artefacts_sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await artefacts_sweeper
        await launcher.stop_all()
        await client.aclose()


def create_app() -> FastAPI:
    """Build a FastAPI app instance. Used by uvicorn and the test suite."""

    settings = get_settings()
    _assert_loopback(settings.host)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = FastAPI(
        title="Pixie",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.mount(
        "/static",
        StaticFiles(directory=settings.static_dir),
        name="static",
    )

    templates = Jinja2Templates(directory=settings.templates_dir)
    # Register Jinja globals so any template can call render_inputs /
    # render_outputs / render_input / render_output without import gymnastics.
    # The implementations are stubs in Phase 4a; Phase 4b/4c swap in real
    # per-type dispatch without touching templates or this registration.
    templates.env.globals["render_inputs"] = render_inputs
    templates.env.globals["render_outputs"] = render_outputs
    templates.env.globals["render_input"] = render_input
    templates.env.globals["render_output"] = render_output
    app.state.templates = templates

    app.include_router(dashboard.router)
    app.include_router(tool_routes.router)
    app.include_router(api.router)
    app.include_router(artefacts_routes.router)
    app.include_router(exports_routes.router)
    app.include_router(library_routes.router)
    app.include_router(reference_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(tools_grid_routes.router)
    app.include_router(workspaces_routes.router)
    return app


# --- typed dependency accessors ----------------------------------------------


def get_launcher(request: Request) -> Launcher:
    return request.app.state.launcher


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.client


LauncherDep = Annotated[Launcher, Depends(get_launcher)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ClientDep = Annotated[httpx.AsyncClient, Depends(get_client)]
