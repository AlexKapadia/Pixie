"""Per-tool routes — run, stream, cancel, replay, history.

Wires the submit-to-output pipeline:

* ``POST /tool/{id}/run``   — coerce the form, dispatch to streaming or
  synchronous proxy, render the output panel with OOB chrome updates.
* ``GET  /tool/{id}/stream`` — SSE relay. Streams events from the tool's
  ``/stream`` endpoint to the browser, honouring client disconnect.
* ``POST /tool/{id}/cancel`` — soft cancel + 5s grace + hard kill per
  DECISIONS #5.
* ``GET  /tool/{id}/runs``  — JSON list for skills + dropdown.
* ``GET  /tool/{id}/runs/{run_id}`` — replay view (inputs pre-filled,
  outputs from the run row).

All failure modes round-trip through ``partials/errors/*.html`` so every
error has a primary action; no JSON 500s reach the user.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from pixie import db, proxy
from pixie.config import Settings
from pixie.discovery import DiscoveredTool, ToolSchema, discover_tools
from pixie.launcher import Launcher, LauncherError, ToolSpawnTimeout
from pixie.routes._coerce import coerce_form

logger = logging.getLogger("pixie.routes.tool")

router = APIRouter()

# Server-Sent Events headers we send on every streaming relay response.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def get_launcher(request: Request) -> Launcher:
    return request.app.state.launcher


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


LauncherDep = Annotated[Launcher, Depends(get_launcher)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
TemplatesDep = Annotated[Jinja2Templates, Depends(get_templates)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_error(
    templates: Jinja2Templates,
    request: Request,
    kind: str,
    ctx: dict[str, Any],
    status_code: int = 200,
) -> HTMLResponse:
    """Render one of the six canonical error shapes into the output panel."""

    return templates.TemplateResponse(
        request, f"partials/errors/{kind}.html", ctx, status_code=status_code
    )


def _venv_missing(tool_path: Any) -> bool:
    from pixie.launcher import _venv_python  # internal but stable

    return not _venv_python(tool_path).exists()


def _find_tool(settings: Settings, tool_id: str) -> DiscoveredTool | None:
    discovered = {t.tool_id: t for t in discover_tools(settings.tools_dir)}
    folder_index = {t.path.name: t for t in discovered.values()}
    return discovered.get(tool_id) or folder_index.get(tool_id)


def _has_streaming_output(schema: ToolSchema) -> bool:
    return any(
        getattr(o, "streaming", False)
        or getattr(o, "type", "") in {"stream_text", "log", "progress"}
        for o in schema.outputs
    )


def _build_input_model(schema: ToolSchema) -> Any:
    """Build an ad-hoc Pydantic model that mirrors a tool's declared inputs.

    Used for server-side validation before we hit the tool's HTTP /run.
    Returns a class whose ``model_validate`` produces a typed dict-ish
    object or raises ``ValidationError`` with field-by-field errors.
    """

    from pydantic import create_model, Field

    fields: dict[str, Any] = {}
    for spec in schema.inputs:
        # Use Any as the type and let the tool itself validate richer
        # shapes (sliders, tables, maps). Pixie's job here is to verify
        # required fields are present, not to re-do tool-side validation.
        if spec.required and spec.default is None:
            fields[spec.key] = (Any, Field(...))
        else:
            fields[spec.key] = (Any | None, Field(default=spec.default))
    return create_model(f"_Inputs_{schema.id}", **fields)


def _tool_chrome_ctx(
    request: Request,
    settings: Settings,
    tool: DiscoveredTool,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared context for partial renders — keeps `tool`, theme, etc. consistent."""

    ctx: dict[str, Any] = {
        "request": request,
        "theme": settings.theme,
        "tool": tool,
        "tool_id": tool.tool_id,
        "tool_label": tool.schema.name if tool.schema else tool.tool_id,
    }
    if extra:
        ctx.update(extra)
    return ctx


def _output_response_with_chrome(
    templates: Jinja2Templates,
    request: Request,
    tool: DiscoveredTool,
    outputs_html: str,
    *,
    run_id: str,
    recent_runs: list[dict[str, Any]],
) -> HTMLResponse:
    """Wrap the output panel HTML with OOB chrome updates (sidebar dot, history)."""

    sidebar_dot_oob = (
        f'<span id="sidebar-dot-{tool.tool_id}" hx-swap-oob="true" '
        f'class="dot dot--running dot--success-flash" aria-label="completed"></span>'
    )
    history_oob = templates.get_template("partials/run_history.html").render(
        request=request,
        tool=tool,
        recent_runs=recent_runs,
        oob=True,
    )
    headers = {"X-Pixie-Run-Done": "1", "X-Pixie-Tool-Id": tool.tool_id}
    body = outputs_html + sidebar_dot_oob + history_oob
    return HTMLResponse(body, headers=headers)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


@router.post("/tool/{tool_id}/run", response_class=HTMLResponse)
async def run_tool(
    tool_id: str,
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    """Coerce form, validate, dispatch streaming vs sync, render outputs."""

    tool = _find_tool(settings, tool_id)
    if tool is None or tool.schema is None:
        return _render_error(
            templates, request, "spawn",
            {
                "tool_id": tool_id, "tool_label": tool_id,
                "stderr": f"Pixie has no tool registered as {tool_id!r}.",
            },
            status_code=404,
        )

    if _venv_missing(tool.path):
        return _render_error(
            templates, request, "venv",
            {
                "tool_id": tool_id,
                "tool_label": tool.schema.name,
                "venv_path": str(tool.path / ".venv"),
            },
        )

    # Coerce + validate the form. Validation errors stay inside the
    # output panel as the standard "run failed" shape.
    form_data = await request.form()
    inputs = coerce_form(list(tool.schema.inputs), form_data)
    try:
        _build_input_model(tool.schema).model_validate(inputs)
    except ValidationError as exc:
        return _render_error(
            templates, request, "run",
            {
                "tool_id": tool_id,
                "tool_label": tool.schema.name,
                "exception_type": "ValidationError",
                "exception_message": "Some inputs failed validation.",
                "traceback": json.dumps(exc.errors(), indent=2),
                "inputs_json": json.dumps(inputs, indent=2),
            },
        )

    run_id = str(uuid.uuid4())

    # Stash inputs for next-time prefill (best-effort; never blocks the run).
    try:
        await db.set_tool_state(settings.db_path, tool.tool_id, last_inputs=inputs)
    except Exception:  # noqa: BLE001
        pass

    # Per-tool serialisation lock if the tool opted out of concurrency.
    serial = getattr(tool.schema, "concurrent", True) is False
    lock_cm = launcher.get_concurrent_lock(tool.tool_id) if serial else None

    # Streaming tools take a different path — return the SSE-opening fragment
    # immediately and let the SSE relay carry both start and events.
    if _has_streaming_output(tool.schema):
        return _render_streaming_open(
            templates, request, tool, run_id, inputs, serial=serial
        )

    async def _run_once() -> dict[str, Any]:
        return await proxy.run_tool(
            launcher, tool, payload={"run_id": run_id, "inputs": inputs},
            run_id=run_id,
            artefacts=getattr(request.app.state, "artefacts", None),
        )

    try:
        if lock_cm is not None:
            async with lock_cm:
                body = await _run_once()
        else:
            body = await _run_once()
    except ToolSpawnTimeout as exc:
        return _render_error(
            templates, request, "timeout",
            {
                "tool_id": tool_id, "tool_label": tool.schema.name,
                "runtime_seconds": tool.schema.max_runtime_seconds,
                "last_log_line": str(exc).splitlines()[-1] if str(exc) else None,
            },
        )
    except LauncherError as exc:
        stderr = getattr(exc, "stderr", None) or str(exc)
        return _render_error(
            templates, request, "spawn",
            {
                "tool_id": tool_id, "tool_label": tool.schema.name,
                "stderr": stderr,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _render_error(
            templates, request, "run",
            {
                "tool_id": tool_id, "tool_label": tool.schema.name,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc(),
                "inputs_json": json.dumps(inputs, indent=2),
            },
        )

    # Prune older runs after a successful finish so the db stays bounded.
    asyncio.create_task(
        db.prune_old_runs_per_tool(settings.db_path, tool.tool_id, keep=100)
    )

    # Render outputs. Thread run_id so output partials can build per-run
    # export URLs via the export_dropdown macro.
    render_outputs = request.app.state.templates.env.globals["render_outputs"]
    outputs_html = str(render_outputs(tool.schema.outputs, body, run_id=run_id))

    recent_runs = await db.list_runs_with_inputs(
        settings.db_path, tool.tool_id, limit=10
    )
    return _output_response_with_chrome(
        templates, request, tool, outputs_html,
        run_id=run_id, recent_runs=recent_runs,
    )


def _render_streaming_open(
    templates: Jinja2Templates,
    request: Request,
    tool: DiscoveredTool,
    run_id: str,
    inputs: dict[str, Any],
    *,
    serial: bool,
) -> HTMLResponse:
    """Fragment that opens an SSE channel to ``/tool/{id}/stream?run_id=...``.

    The browser receives the streaming output cards (empty placeholders),
    wrapped in an ``hx-ext="sse"`` div that opens the connection. Each
    output panel inside has ``sse-swap="output:<key>"`` so per-event
    payloads land in the correct panel.

    The inputs are sent up-front by encoding them as a JSON string body
    on the SSE GET via the `inputs` query param — but URLs cap fast, so
    instead we POST them via a one-shot helper endpoint and let the SSE
    GET take only `run_id`. We persist `inputs` in the run row via
    ``record_run_start`` here and the relay endpoint reads them back.
    """

    settings: Settings = request.app.state.settings
    payload = {"run_id": run_id, "inputs": inputs}
    # Record start so the SSE handler can recover inputs for the actual
    # /run POST it does in parallel.
    asyncio.create_task(
        db.record_run_start(settings.db_path, run_id, tool.tool_id, payload)
    )

    render_outputs = request.app.state.templates.env.globals["render_outputs"]
    # Pre-render every output as its empty-state shell with stable target ids.
    outputs_html = str(render_outputs(tool.schema.outputs, None))

    stream_url = f"/tool/{tool.tool_id}/stream?run_id={run_id}"
    cancel_url = f"/tool/{tool.tool_id}/cancel?run_id={run_id}"
    body = (
        f'<div class="output-streaming" '
        f'data-run-id="{run_id}" '
        f'hx-ext="sse" sse-connect="{stream_url}" sse-close="done">'
        f'<div class="output-streaming__header">'
        f'<span class="badge badge--running">'
        f'<span class="dot dot--running dot--pulse"></span> Running…'
        f'</span>'
        f'<span class="t-meta mono" data-pixie-elapsed>0.0s</span>'
        f'<span style="flex:1"></span>'
        f'<button type="button" class="btn btn--ghost btn--sm cancel-btn" '
        f'hx-post="{cancel_url}" hx-target="#output-panel" hx-swap="innerHTML" '
        f'style="opacity:0;transition:opacity .3s" data-pixie-cancel>'
        f'Cancel</button>'
        f'</div>'
        f'{outputs_html}'
        f'</div>'
        f'<script>(function(){{'
        f'var host=document.currentScript.previousElementSibling;'
        f'var start=Date.now();'
        f'var el=host&&host.querySelector("[data-pixie-elapsed]");'
        f'var cancel=host&&host.querySelector("[data-pixie-cancel]");'
        f'var t=setInterval(function(){{'
        f'  var s=(Date.now()-start)/1000;'
        f'  if(el)el.textContent=s.toFixed(1)+"s";'
        f'  if(cancel&&s>2)cancel.style.opacity="1";'
        f'}},100);'
        f'host&&host.addEventListener("htmx:sseClose",function(){{clearInterval(t);'
        f'  var carets=host.querySelectorAll(".stream-caret");'
        f'  carets.forEach(function(c){{c.style.display="none";}});'
        f'  if(cancel)cancel.style.display="none";'
        f'  var b=host.querySelector(".badge--running");'
        f'  if(b){{b.classList.remove("badge--running");b.classList.add("badge");b.textContent="Done";}}'
        f'}});'
        f'}})();</script>'
    )
    return HTMLResponse(body)


# ---------------------------------------------------------------------------
# SSE relay
# ---------------------------------------------------------------------------


@router.get("/tool/{tool_id}/stream")
async def stream_tool(
    tool_id: str,
    run_id: str,
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
) -> StreamingResponse:
    """Relay SSE events from the tool's ``/stream`` to the browser.

    Rewrites the upstream's named events (or default ``data:`` lines) to
    ``event: output:<key>`` so htmx's ``sse-swap="output:<key>"`` lands
    payloads in the correct panel. Emits a terminal ``event: done`` so
    ``sse-close="done"`` closes the connection cleanly.
    """

    tool = _find_tool(settings, tool_id)
    if tool is None or tool.schema is None:
        return StreamingResponse(
            _error_event_stream(f"tool {tool_id!r} not found"),
            media_type="text/event-stream", headers=SSE_HEADERS,
            status_code=404,
        )

    # Recover inputs from the run row we wrote when we returned the open frag.
    row = await db.get_run(settings.db_path, run_id)
    if row is None:
        return StreamingResponse(
            _error_event_stream(f"run {run_id!r} not found"),
            media_type="text/event-stream", headers=SSE_HEADERS,
            status_code=404,
        )
    try:
        payload = json.loads(row.get("inputs_json") or "{}")
    except json.JSONDecodeError:
        payload = {"run_id": run_id, "inputs": {}}

    async def _generator() -> Any:
        try:
            async for raw_chunk in proxy.stream_tool(
                launcher, tool, payload=payload, run_id=run_id,
                artefacts=getattr(request.app.state, "artefacts", None),
            ):
                if await request.is_disconnected():
                    # Client gone — cancel upstream and bail.
                    await proxy.cancel_tool(launcher, tool, run_id)
                    break
                rewritten = _rewrite_events(raw_chunk)
                yield rewritten
            # Terminal done event so the browser closes sse-connect.
            yield b"event: done\ndata: {}\n\n"
        except (LauncherError, Exception) as exc:  # noqa: BLE001
            payload_err = json.dumps({"message": str(exc)})
            yield f"event: error\ndata: {payload_err}\n\n".encode("utf-8")
            yield b"event: done\ndata: {}\n\n"

    return StreamingResponse(
        _generator(), media_type="text/event-stream", headers=SSE_HEADERS
    )


async def _error_event_stream(message: str) -> Any:
    yield f"event: error\ndata: {json.dumps({'message': message})}\n\n".encode("utf-8")
    yield b"event: done\ndata: {}\n\n"


def _rewrite_events(chunk: bytes) -> bytes:
    """Rewrite upstream SSE bytes so each event is named ``output:<key>``.

    Upstream tools emit named events like ``event: completion\\ndata: ...\\n\\n``
    where the event name IS the output key. We prefix with ``output:`` so
    htmx-ext-sse's ``sse-swap="output:<key>"`` matches. Pass through other
    framing (comments, default events) unmodified.
    """

    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return chunk
    out_lines: list[str] = []
    for line in text.split("\n"):
        if line.startswith("event: ") and not line.startswith("event: output:") \
           and not line.startswith("event: done") \
           and not line.startswith("event: error"):
            name = line[len("event: "):]
            out_lines.append(f"event: output:{name}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines).encode("utf-8")


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@router.post("/tool/{tool_id}/cancel", response_class=HTMLResponse)
async def cancel_run(
    tool_id: str,
    run_id: str,
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    """Soft cancel then hard kill after 5s, per DECISIONS #5."""

    tool = _find_tool(settings, tool_id)
    if tool is None:
        return HTMLResponse(
            '<div class="output-empty">Tool not found.</div>', status_code=404
        )
    hard_killed = await proxy.cancel_tool_hard(launcher, tool, run_id, soft_grace=5.0)
    await db.record_run_cancelled(settings.db_path, run_id)

    msg = (
        "Run cancelled. The tool process was hard-stopped because it did "
        "not honour the soft cancel."
        if hard_killed
        else "Run cancelled."
    )
    return HTMLResponse(
        f'<div class="output-empty" role="status">'
        f'<span class="badge">cancelled</span> '
        f'<span class="t-meta">{msg}</span>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Run history list (JSON for skills, dropdown)
# ---------------------------------------------------------------------------


@router.get("/tool/{tool_id}/runs", response_class=JSONResponse)
async def list_tool_runs(
    tool_id: str,
    settings: SettingsDep,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the recent runs for a tool with one-line inputs summaries."""

    rows = await db.list_runs_with_inputs(settings.db_path, tool_id, limit=limit)
    return rows


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@router.get("/tool/{tool_id}/runs/{run_id}", response_class=HTMLResponse)
async def get_run(
    tool_id: str,
    run_id: str,
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    """Replay a past run: pre-fill inputs and show its outputs (or oversize hint)."""

    tool = _find_tool(settings, tool_id)
    if tool is None or tool.schema is None:
        return _render_error(
            templates, request, "spawn",
            {
                "tool_id": tool_id, "tool_label": tool_id,
                "stderr": f"Pixie has no tool registered as {tool_id!r}.",
            },
            status_code=404,
        )

    row = await db.get_run(settings.db_path, run_id)
    if row is None:
        return _render_error(
            templates, request, "validation",
            {
                "tool_id": tool_id,
                "tool_label": tool.schema.name,
                "report": {
                    "tool_id": tool_id, "overall": "warn",
                    "checks": [{
                        "name": "Run history", "status": "warn",
                        "message": f"Run {run_id!r} is not in the history.",
                        "details": None,
                    }],
                },
            },
            status_code=404,
        )

    try:
        inputs_envelope = json.loads(row.get("inputs_json") or "{}")
    except json.JSONDecodeError:
        inputs_envelope = {}
    last_inputs = inputs_envelope.get("inputs") if isinstance(inputs_envelope, dict) else {}
    if not isinstance(last_inputs, dict):
        last_inputs = inputs_envelope if isinstance(inputs_envelope, dict) else {}

    outputs: dict[str, Any] | None = None
    outputs_dropped = False
    if row.get("outputs_json"):
        try:
            outputs = json.loads(row["outputs_json"])
            if isinstance(outputs, dict) and outputs.get("_pixie_dropped"):
                outputs_dropped = True
                outputs = None
        except json.JSONDecodeError:
            outputs = None

    # If this is an htmx swap into the output panel only, return just the
    # outputs panel innerHTML. Otherwise, render the whole tool view.
    is_htmx = request.headers.get("hx-request", "").lower() == "true"
    target = request.headers.get("hx-target", "").lower()
    if is_htmx and target == "output-panel":
        render_outputs = request.app.state.templates.env.globals["render_outputs"]
        if outputs_dropped:
            return HTMLResponse(
                '<div class="output-empty"><span class="t-meta">'
                'This run\'s outputs exceeded the 1MB cap and were not stored. '
                'Re-run with the same inputs to regenerate.</span></div>'
            )
        return HTMLResponse(str(render_outputs(
            tool.schema.outputs, outputs or {}, run_id=run_id,
        )))

    # Full tool view re-render — build context through the same helpers
    # the live tool view uses so the sidebar + base context match exactly.
    from pixie.routes.dashboard import (  # local: avoid cycle
        _base_context, _sidebar_context, _runtime_status,
    )

    sidebar = await _sidebar_context(settings, launcher)
    setattr(tool, "status", _runtime_status(launcher, tool))
    setattr(tool, "has_required_secrets_missing", False)
    setattr(tool, "port", None)
    setattr(tool, "pid", None)

    ctx = _base_context(request, settings)
    ctx.update(
        sidebar_groups=sidebar["sidebar_groups"],
        running_count=sidebar["running_count"],
        sidebar_workspaces=sidebar.get("sidebar_workspaces", []),
        active_workspace_id=sidebar.get("active_workspace_id"),
        active_workspace_name=sidebar.get("active_workspace_name"),
        sidebar_favourites=sidebar.get("sidebar_favourites", []),
        sidebar_recent=sidebar.get("sidebar_recent", []),
        archived_count=sidebar.get("archived_count", 0),
        archived_tool_ids=sidebar.get("archived_tool_ids", []),
        sidebar_total_tools=sidebar.get("sidebar_total_tools", 0),
        active_tool_id=tool.tool_id,
        tool=tool,
        recent_runs=await db.list_runs_with_inputs(
            settings.db_path, tool.tool_id, limit=10
        ),
        last_inputs=last_inputs,
        last_outputs=outputs if not outputs_dropped else None,
        viewing_run_id=run_id,
        outputs_dropped=outputs_dropped,
        saved_run=True,
    )
    # Always render the full page; htmx extracts #pixie-main-shell from
    # the response and swaps header + body together (see base.html).
    return templates.TemplateResponse(request, "tool.html", ctx)


async def _sidebar_for_replay(
    settings: Settings, launcher: Launcher
) -> dict[str, Any]:
    """Lightweight sidebar context for the replay full-page render."""

    from pixie.routes.dashboard import _sidebar_context  # local: avoid cycle

    return await _sidebar_context(settings, launcher)
