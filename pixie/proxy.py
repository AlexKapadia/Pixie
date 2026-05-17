"""HTTP proxy from Pixie routes to tool subprocesses.

Forwards ``/run``, ``/stream`` (SSE), and ``/cancel`` to the tool's
local HTTP server using one shared ``httpx.AsyncClient`` created in
the app lifespan. Loopback only; never crosses a network interface.
For SSE, ``aiter_raw()`` preserves event framing verbatim.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from pixie import artefacts as artefacts_mod
from pixie import db
from pixie.artefacts import ArtefactRegistry, RunArtefactsContext
from pixie.config import Settings
from pixie.discovery import DiscoveredTool
from pixie.launcher import Launcher, LauncherError

logger = logging.getLogger("pixie.proxy")


async def run_tool(
    launcher: Launcher,
    tool: DiscoveredTool,
    payload: dict[str, Any],
    run_id: str,
    *,
    artefacts: ArtefactRegistry | None = None,
) -> dict[str, Any]:
    """Ensure the tool is running, POST to ``/run``, record the result in db."""

    if tool.schema is None:
        raise LauncherError(f"tool {tool.tool_id!r} has no valid schema")
    settings: Settings = launcher.settings
    await db.record_run_start(settings.db_path, run_id, tool.tool_id, payload)
    running: Any = None
    # Pre-create the artefact dir + start the quota watchdog before the
    # subprocess starts writing. See RESEARCH_output_persistence s1.3.
    run_ctx: RunArtefactsContext | None = None
    watchdog: asyncio.Task[None] | None = None
    if artefacts is not None:
        run_dir = artefacts.get_run_dir(tool.tool_id, run_id)
        run_ctx = RunArtefactsContext(
            run_id=run_id, tool_id=tool.tool_id, artefacts_dir=run_dir,
        )
        max_bytes = settings.max_artefact_bytes_per_run
        watchdog = asyncio.create_task(
            artefacts_mod.quota_watchdog(
                run_ctx, max_bytes=max_bytes,
                on_exceeded=lambda _c: asyncio.create_task(
                    launcher.stop(tool.tool_id)
                ),
            ),
            name=f"pixie-quota-{run_id}",
        )
        run_ctx.watchdog_task = watchdog
        payload.setdefault("_pixie", {})
        if isinstance(payload["_pixie"], dict):
            payload["_pixie"]["run_id"] = run_id
            payload["_pixie"]["artefacts_dir"] = str(run_dir)
    try:
        port = await launcher.ensure_running(tool)
        running = launcher.processes.get(tool.tool_id)
        if running is not None:
            running.in_flight_runs.add(run_id)
        timeout = httpx.Timeout(
            tool.schema.max_runtime_seconds + 5.0,
            connect=2.0,
        )
        headers = {}
        if run_ctx is not None:
            headers["X-Pixie-Run-Id"] = run_id
            headers["X-Pixie-Artefacts-Dir"] = str(run_ctx.artefacts_dir)
        response = await launcher.client.post(
            f"http://127.0.0.1:{port}/run",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        launcher.touch(tool.tool_id)
        await db.record_run_finish(settings.db_path, run_id, body)
        if artefacts is not None and run_ctx is not None:
            declared = {o.key for o in (tool.schema.outputs or [])}
            try:
                await artefacts_mod.register_run_artefacts(
                    artefacts, tool.tool_id, run_id,
                    run_dir=run_ctx.artefacts_dir,
                    declared_output_keys=declared,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("post-run artefact registration failed: %s", exc)
        return body
    except httpx.HTTPStatusError as exc:
        stderr_tail = _stderr_for(launcher, tool.tool_id)
        message = (
            f"tool {tool.tool_id!r} returned {exc.response.status_code}: "
            f"{exc.response.text[:500]}\n--- stderr ---\n{stderr_tail}"
        )
        await db.record_run_error(settings.db_path, run_id, message)
        raise LauncherError(message) from exc
    except Exception as exc:
        stderr_tail = _stderr_for(launcher, tool.tool_id)
        message = f"{exc}\n--- stderr ---\n{stderr_tail}"
        await db.record_run_error(settings.db_path, run_id, message)
        raise
    finally:
        if running is not None:
            running.in_flight_runs.discard(run_id)
        if watchdog is not None and not watchdog.done():
            watchdog.cancel()


async def stream_tool(
    launcher: Launcher,
    tool: DiscoveredTool,
    payload: dict[str, Any],
    run_id: str,
    *,
    artefacts: ArtefactRegistry | None = None,
) -> AsyncIterator[bytes]:
    """Trigger the run, then yield raw SSE bytes from the tool's ``/stream``.

    Returned as an async generator. The route handler wraps these bytes
    in ``StreamingResponse`` for the dashboard's own SSE relay.
    """

    if tool.schema is None:
        raise LauncherError(f"tool {tool.tool_id!r} has no valid schema")
    settings: Settings = launcher.settings
    await db.record_run_start(settings.db_path, run_id, tool.tool_id, payload)
    run_ctx: RunArtefactsContext | None = None
    if artefacts is not None:
        run_dir = artefacts.get_run_dir(tool.tool_id, run_id)
        run_ctx = RunArtefactsContext(
            run_id=run_id, tool_id=tool.tool_id, artefacts_dir=run_dir,
        )
        payload.setdefault("_pixie", {})
        if isinstance(payload["_pixie"], dict):
            payload["_pixie"]["run_id"] = run_id
            payload["_pixie"]["artefacts_dir"] = str(run_dir)
    port = await launcher.ensure_running(tool)
    running = launcher.processes.get(tool.tool_id)
    if running is not None:
        running.in_flight_runs.add(run_id)
    headers = {}
    if run_ctx is not None:
        headers["X-Pixie-Run-Id"] = run_id
        headers["X-Pixie-Artefacts-Dir"] = str(run_ctx.artefacts_dir)
    # Kick the run; the tool returns immediately and produces events on /stream.
    await launcher.client.post(
        f"http://127.0.0.1:{port}/run",
        json=payload, headers=headers,
        timeout=httpx.Timeout(5.0, connect=2.0),
    )
    url = f"http://127.0.0.1:{port}/stream"
    try:
        async with launcher.client.stream(
            "GET",
            url,
            params={"run_id": run_id},
            timeout=httpx.Timeout(None, connect=2.0),
        ) as upstream:
            batch_counter = 0
            async for chunk in upstream.aiter_raw():
                launcher.touch(tool.tool_id)
                yield chunk
                # Incremental artefact registration during long-running
                # streams (RESEARCH_output_persistence s2.3 mode C).
                if artefacts is not None and run_ctx is not None:
                    batch_counter += 1
                    if batch_counter % 8 == 0:
                        try:
                            declared = {o.key for o in (tool.schema.outputs or [])}
                            await artefacts_mod.register_run_artefacts(
                                artefacts, tool.tool_id, run_id,
                                run_dir=run_ctx.artefacts_dir,
                                declared_output_keys=declared,
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("partial scan failed: %s", exc)
        await db.record_run_finish(settings.db_path, run_id, {})
        if artefacts is not None and run_ctx is not None:
            try:
                declared = {o.key for o in (tool.schema.outputs or [])}
                await artefacts_mod.register_run_artefacts(
                    artefacts, tool.tool_id, run_id,
                    run_dir=run_ctx.artefacts_dir,
                    declared_output_keys=declared,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("final stream artefact scan failed: %s", exc)
    except Exception as exc:
        await db.record_run_error(settings.db_path, run_id, str(exc))
        raise
    finally:
        if running is not None:
            running.in_flight_runs.discard(run_id)


async def cancel_tool(
    launcher: Launcher, tool: DiscoveredTool, run_id: str
) -> None:
    """Best-effort POST to the tool's ``/cancel`` endpoint."""

    running = launcher.processes.get(tool.tool_id)
    if running is None:
        return
    try:
        await launcher.client.post(
            f"http://127.0.0.1:{running.port}/cancel",
            params={"run_id": run_id},
            timeout=httpx.Timeout(5.0, connect=1.0),
        )
    except httpx.HTTPError as exc:
        logger.warning("cancel for %s/%s failed: %s", tool.tool_id, run_id, exc)


async def cancel_tool_hard(
    launcher: Launcher, tool: DiscoveredTool, run_id: str, soft_grace: float = 5.0
) -> bool:
    """Soft cancel, then hard-stop the subprocess if the run is still in flight.

    Returns ``True`` if a hard kill happened. Per DECISIONS #5, the hard
    cancel respawns the tool on next click rather than babysitting it.
    """

    import asyncio as _asyncio

    await cancel_tool(launcher, tool, run_id)
    deadline = _asyncio.get_running_loop().time() + soft_grace
    while _asyncio.get_running_loop().time() < deadline:
        running = launcher.processes.get(tool.tool_id)
        if running is None or run_id not in running.in_flight_runs:
            return False
        await _asyncio.sleep(0.25)
    # Still in flight: kill the process. Next click respawns lazily.
    await launcher.stop(tool.tool_id)
    await db.record_run_cancelled(launcher.settings.db_path, run_id)
    return True


def _stderr_for(launcher: Launcher, tool_id: str) -> str:
    running = launcher.processes.get(tool_id)
    return running.stderr_ring.snapshot() if running else ""
