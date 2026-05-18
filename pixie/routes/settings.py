"""Global and per-tool settings routes.

Hosts:

* ``GET /settings`` — global settings page (theme, accent, density,
  warm-keep, dev mode, maintenance, about).
* ``POST /settings`` — persist global settings changes.
* ``POST /settings/revalidate-all`` — kick off background validation.
* ``GET /settings/revalidate-status`` — poll fragment for the above.
* ``POST /settings/clear-history`` — drop run history (per tool or all).
* ``POST /settings/vacuum`` — VACUUM ``pixie.db``.
* ``GET /tool/{tool_id}/settings`` — per-tool settings page.
* ``POST /tool/{tool_id}/secrets/{key}`` — write a secret.
* ``DELETE /tool/{tool_id}/secrets/{key}`` — clear a secret.
* ``POST /tool/{tool_id}/overrides`` — write resource overrides.
* ``POST /tool/{tool_id}/validate-now`` — render the validation panel.
* ``POST /tool/{tool_id}/open-folder`` — reveal tool folder in OS browser.
* ``POST /tool/{tool_id}/hot-reload`` — stop the warm subprocess.

Every action returns either the full settings page or an htmx fragment
that the page swaps in place. No JSON 500s — failures render as toasts
through ``HX-Trigger`` headers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from pixie import db, secrets as pixie_secrets
from pixie.config import Settings
from pixie.discovery import DiscoveredTool, discover_tools
from pixie.launcher import Launcher
from pixie.validator import validate_tool

logger = logging.getLogger("pixie.routes.settings")

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


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
# Shared helpers
# ---------------------------------------------------------------------------


GLOBAL_KEYS = (
    "theme", "accent", "density",
    "warm_keep_max", "warm_keep_seconds", "developer_mode",
)

ACCENT_CHOICES = ("indigo", "slate", "forest", "ember")
DENSITY_CHOICES = ("compact", "comfortable", "airy")

# Theme registry. Keep in lockstep with the THEMES map in pixie.js and the
# [data-theme="<id>"] blocks in pixie.css. `variant` is "light" or "dark"
# and decides which sub-palette the per-theme accent override picks.
# "auto" is a meta-choice that resolves to light/dark via matchMedia client-side.
THEMES: dict[str, dict[str, str]] = {
    "auto":              {"label": "Auto",             "variant": "light"},
    "light":             {"label": "Light",            "variant": "light"},
    "dark":              {"label": "Dark",             "variant": "dark"},
    "bloomberg":         {"label": "Bloomberg",        "variant": "dark"},
    "solarized-light":   {"label": "Solarized Light",  "variant": "light"},
    "solarized-dark":    {"label": "Solarized Dark",   "variant": "dark"},
    "dracula":           {"label": "Dracula",          "variant": "dark"},
    "nord":              {"label": "Nord",             "variant": "dark"},
    "monokai":           {"label": "Monokai",          "variant": "dark"},
    "github-dark":       {"label": "GitHub Dark",      "variant": "dark"},
    "gruvbox-dark":      {"label": "Gruvbox Dark",     "variant": "dark"},
    "sepia":             {"label": "Sepia",            "variant": "light"},
    "high-contrast":     {"label": "High Contrast",    "variant": "light"},
    "catppuccin-latte":  {"label": "Catppuccin Latte", "variant": "light"},
}
THEME_CHOICES = tuple(THEMES.keys())


async def load_global_settings(settings: Settings) -> dict[str, Any]:
    """Read every persisted global setting, applying built-in defaults."""

    async def _get(key: str, default: Any) -> Any:
        raw = await db.get_setting(settings.db_path, key)
        return raw if raw is not None else default

    theme = await _get("theme", settings.theme)
    accent = await _get("accent", settings.accent)
    density = await _get("density", settings.density)
    warm_keep_max = await _get("warm_keep_max", str(settings.warm_keep_max))
    warm_keep_seconds = await _get(
        "warm_keep_seconds", str(settings.warm_keep_seconds)
    )
    dev_mode_raw = await _get(
        "developer_mode", "1" if settings.developer_mode else "0"
    )
    return {
        "theme": theme if theme in THEME_CHOICES else "light",
        "accent": accent if accent in ACCENT_CHOICES else "indigo",
        "density": density if density in DENSITY_CHOICES else "comfortable",
        "warm_keep_max": int(warm_keep_max) if str(warm_keep_max).isdigit() else 5,
        "warm_keep_seconds": (
            int(warm_keep_seconds) if str(warm_keep_seconds).isdigit() else 300
        ),
        "developer_mode": str(dev_mode_raw) in ("1", "true", "True", "on"),
    }


def _resolve_tool(settings: Settings, tool_id: str) -> DiscoveredTool | None:
    discovered = discover_tools(settings.tools_dir)
    by_id = {t.tool_id: t for t in discovered}
    folder_index = {t.path.name: t for t in discovered}
    return by_id.get(tool_id) or folder_index.get(tool_id)


def _toast_header(text: str, kind: str = "success") -> dict[str, str]:
    """Build an HX-Trigger header that fires the pixie:toast event."""

    payload = {"pixie:toast": {"text": text, "kind": kind}}
    return {"HX-Trigger": json.dumps(payload)}


async def _sidebar_payload(
    settings: Settings, launcher: Launcher
) -> dict[str, Any]:
    """Mirrors dashboard._sidebar_context but free of circular imports."""

    discovered = discover_tools(settings.tools_dir)
    entries: list[dict[str, Any]] = []
    running_count = 0
    for tool in discovered:
        report = await db.latest_validation_report(settings.db_path, tool.tool_id)
        validation = (report.get("overall") if report else None) or "unchecked"
        if tool.schema is None:
            entries.append({
                "tool_id": tool.tool_id,
                "name": tool.tool_id,
                "category": "Uncategorised",
                "description": tool.parse_error or "Tool failed to parse",
                "icon": "alert-triangle",
                "status": "failed",
                "validation": validation,
            })
            continue
        if launcher.is_running(tool.tool_id):
            status = "running"
            running_count += 1
        else:
            status = "dormant"
        entries.append({
            "tool_id": tool.tool_id,
            "name": tool.schema.name,
            "category": tool.schema.category or "Uncategorised",
            "description": tool.schema.description,
            "icon": tool.schema.icon,
            "status": status,
            "validation": validation,
        })

    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        groups.setdefault(entry["category"], []).append(entry)
    return {
        "sidebar_groups": list(groups.items()),
        "running_count": running_count,
        "discovered": discovered,
    }


def _base_context(
    request: Request, settings: Settings, persisted: dict[str, Any]
) -> dict[str, Any]:
    return {
        "request": request,
        "theme": persisted["theme"] if persisted["theme"] != "auto" else settings.theme,
        "version": "0.1.0",
        "port": settings.port,
        "developer_mode": persisted["developer_mode"],
        "persisted_settings": persisted,
    }


# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
async def global_settings_page(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    sidebar = await _sidebar_payload(settings, launcher)
    persisted = await load_global_settings(settings)
    discovered: list[DiscoveredTool] = sidebar["discovered"]
    uptime_s = int(
        time.monotonic()
        - getattr(request.app.state, "start_monotonic", time.monotonic())
    )
    ctx = _base_context(request, settings, persisted)
    ctx.update(
        sidebar_groups=sidebar["sidebar_groups"],
        running_count=sidebar["running_count"],
        active_tool_id=None,
        tool_count=sum(1 for t in discovered if t.schema is not None),
        broken_tool_count=sum(1 for t in discovered if t.schema is None),
        warm_count=len(launcher.list_running()),
        db_size=await db.db_size_bytes(settings.db_path),
        uptime_seconds=uptime_s,
        tools_dir=str(settings.tools_dir),
        accent_choices=ACCENT_CHOICES,
        density_choices=DENSITY_CHOICES,
        theme_choices=THEME_CHOICES,
        themes=THEMES,
        revalidate_status=getattr(request.app.state, "revalidate_status", None),
    )
    template = (
        "partials/settings_global_body.html"
        if request.headers.get("hx-request", "").lower() == "true"
        else "settings.html"
    )
    return templates.TemplateResponse(request, template, ctx)


# Allowlist of preference keys writable through /settings/preference, with the
# validator used to normalise the raw string into a DB value. Each validator
# returns the canonicalised value or raises HTTPException(400) on bad input.
def _validate_theme(v: str) -> str:
    if v not in THEME_CHOICES:
        raise HTTPException(status_code=400, detail="unknown theme")
    return v


def _validate_accent(v: str) -> str:
    if v not in ACCENT_CHOICES:
        raise HTTPException(status_code=400, detail="unknown accent")
    return v


def _validate_density(v: str) -> str:
    if v not in DENSITY_CHOICES:
        raise HTTPException(status_code=400, detail="unknown density")
    return v


def _validate_bool_flag(v: Any) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    s = str(v).strip().lower()
    if s in ("1", "true", "on", "yes"):
        return "1"
    if s in ("0", "false", "off", "no", ""):
        return "0"
    raise HTTPException(status_code=400, detail="boolean expected")


def _validate_warm_keep_max(v: Any) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="integer expected") from exc
    return str(max(1, min(n, 64)))


def _validate_warm_keep_seconds(v: Any) -> str:
    try:
        n = int(v)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="integer expected") from exc
    return str(max(0, min(n, 24 * 3600)))


_PREFERENCE_VALIDATORS: dict[str, Any] = {
    "theme": _validate_theme,
    "accent": _validate_accent,
    "density": _validate_density,
    "developer_mode": _validate_bool_flag,
    "warm_keep_max": _validate_warm_keep_max,
    "warm_keep_seconds": _validate_warm_keep_seconds,
}


async def _read_body(request: Request) -> dict[str, Any]:
    """Parse a request body as either JSON or form-encoded data.

    Content-Type drives the decision so the same endpoint accepts
    ``application/json`` (htmx with json-enc, fetch, programmatic
    clients) and ``application/x-www-form-urlencoded`` / multipart
    (FastAPI ``Form(...)`` callers, plain HTML form submits).

    Empty / missing bodies yield ``{}`` rather than raising — callers
    enforce required keys with explicit ``KeyError`` handling.
    """

    ctype = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if ctype == "application/json":
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="JSON body must be an object"
            )
        return payload
    # Form, multipart, or no body at all -> let FastAPI's form parser handle it.
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001 — surface as 400
        raise HTTPException(status_code=400, detail="invalid form body") from exc
    return {k: v for k, v in form.items()}


@router.post("/settings/preference", response_class=Response)
async def save_preference(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
) -> Response:
    """Persist a single preference immediately.

    The settings page's Theme / Accent / Density radios POST here from their
    onchange handler so the chosen value sticks across htmx swaps — without
    waiting for the Save button or losing the rest of the form state. The
    same endpoint also takes ``developer_mode`` / ``warm_keep_max`` /
    ``warm_keep_seconds`` so programmatic clients can flip behaviour
    without rendering the whole form.

    Accepts both ``application/x-www-form-urlencoded`` and
    ``application/json`` bodies of ``{key, value}``.

    Returns 204 (no body) so htmx doesn't replace anything; the client has
    already updated the DOM via Pixie.setTheme/Accent/Density.
    """

    body = await _read_body(request)
    key = body.get("key")
    if key is None:
        raise HTTPException(status_code=400, detail="missing 'key'")
    if not isinstance(key, str) or key not in _PREFERENCE_VALIDATORS:
        raise HTTPException(status_code=400, detail="unknown preference key")
    if "value" not in body:
        raise HTTPException(status_code=400, detail="missing 'value'")
    raw_value = body["value"]
    canonical = _PREFERENCE_VALIDATORS[key](raw_value)

    await db.set_setting(settings.db_path, key, canonical)

    # Reflect runtime-impacting fields into the live Settings/launcher so the
    # change takes effect immediately, mirroring the legacy /settings handler.
    if key == "warm_keep_max":
        launcher.settings.warm_keep_max = int(canonical)
    elif key == "warm_keep_seconds":
        launcher.settings.warm_keep_seconds = int(canonical)
    elif key == "developer_mode":
        settings.developer_mode = canonical == "1"
    # SSR payload reads from DB on every request via middleware, so no
    # in-memory mirror needed for theme/accent/density. The in-memory
    # Settings.theme is "light"/"dark" only and would collapse rich theme
    # names like "dracula" — we deliberately don't touch it here.
    return Response(status_code=204)


@router.post("/settings/theme", response_class=Response)
async def save_theme(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
) -> Response:
    """Alias for ``POST /settings/preference`` with ``key=theme``.

    Convenience endpoint that takes a single ``theme`` field (form or
    JSON) and validates it against :data:`THEME_CHOICES`. Returns 204
    on success, 400 on an unknown theme.
    """

    body = await _read_body(request)
    if "theme" not in body:
        raise HTTPException(status_code=400, detail="missing 'theme'")
    theme = _validate_theme(str(body["theme"]))
    await db.set_setting(settings.db_path, "theme", theme)
    return Response(status_code=204)


@router.post("/settings", response_class=HTMLResponse)
async def save_global_settings(
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    """Persist every Appearance + Behaviour field as one transaction.

    Accepts both ``application/x-www-form-urlencoded`` (the default
    HTML form submit + htmx default) and ``application/json`` bodies
    so programmatic clients and htmx-with-json-enc both work.
    """

    body = await _read_body(request)
    theme = str(body.get("theme", "light"))
    accent = str(body.get("accent", "indigo"))
    density = str(body.get("density", "comfortable"))
    try:
        warm_keep_max = int(body.get("warm_keep_max", 5) or 5)
    except (TypeError, ValueError):
        warm_keep_max = 5
    try:
        warm_keep_seconds = int(body.get("warm_keep_seconds", 300) or 300)
    except (TypeError, ValueError):
        warm_keep_seconds = 300
    dev_raw = body.get("developer_mode", "")
    if isinstance(dev_raw, bool):
        dev_flag = dev_raw
    else:
        dev_flag = str(dev_raw).strip().lower() in ("1", "true", "on", "yes")

    if theme not in THEME_CHOICES:
        theme = "light"
    if accent not in ACCENT_CHOICES:
        accent = "indigo"
    if density not in DENSITY_CHOICES:
        density = "comfortable"
    warm_keep_max = max(1, min(int(warm_keep_max), 64))
    warm_keep_seconds = max(0, min(int(warm_keep_seconds), 24 * 3600))

    await db.set_setting(settings.db_path, "theme", theme)
    await db.set_setting(settings.db_path, "accent", accent)
    await db.set_setting(settings.db_path, "density", density)
    await db.set_setting(settings.db_path, "warm_keep_max", str(warm_keep_max))
    await db.set_setting(
        settings.db_path, "warm_keep_seconds", str(warm_keep_seconds)
    )
    await db.set_setting(settings.db_path, "developer_mode", "1" if dev_flag else "0")

    # Apply runtime-impacting fields straight away so the launcher honours
    # the new values without a restart.
    launcher.settings.warm_keep_max = warm_keep_max
    launcher.settings.warm_keep_seconds = warm_keep_seconds
    settings.developer_mode = dev_flag
    # settings.theme is the SSR fallback for the <html data-theme> attribute;
    # it must be a base palette name (light/dark) the CSS can render before JS
    # hydrates. Themes whose variant is "dark" fall back to "dark"; the rest
    # to "light". The full theme id is still persisted in pixie.db and applied
    # by Pixie.setTheme as soon as the payload script parses.
    settings.theme = "dark" if THEMES.get(theme, {}).get("variant") == "dark" else "light"
    settings.accent = accent
    settings.density = density  # type: ignore[assignment]

    response = await global_settings_page(request, settings, launcher, templates)
    response.headers.update(_toast_header("Settings saved."))
    return response


# ---------------------------------------------------------------------------
# Background re-validation status (in-memory)
# ---------------------------------------------------------------------------


@dataclass
class RevalidateStatus:
    started_at: float
    total: int
    done: int = 0
    current: str | None = None
    finished: bool = False
    summary: dict[str, int] = field(
        default_factory=lambda: {"pass": 0, "warn": 0, "fail": 0}
    )


async def _run_revalidation(app_state: Any, settings: Settings) -> None:
    status: RevalidateStatus = app_state.revalidate_status
    try:
        tools = [
            t for t in discover_tools(settings.tools_dir) if t.schema is not None
        ]
        status.total = len(tools)
        for tool in tools:
            status.current = tool.tool_id
            try:
                report = await validate_tool(tool.path, save_to_db=True)
                status.summary[report.overall] = (
                    status.summary.get(report.overall, 0) + 1
                )
            except Exception as exc:  # noqa: BLE001 — keep iterating
                logger.warning("revalidate %s failed: %s", tool.tool_id, exc)
                status.summary["fail"] = status.summary.get("fail", 0) + 1
            status.done += 1
    finally:
        status.finished = True
        status.current = None


@router.post("/settings/revalidate-all", response_class=HTMLResponse)
async def revalidate_all(
    request: Request,
    settings: SettingsDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    existing = getattr(request.app.state, "revalidate_status", None)
    if existing is None or existing.finished:
        request.app.state.revalidate_status = RevalidateStatus(
            started_at=time.monotonic(), total=0
        )
        asyncio.create_task(
            _run_revalidation(request.app.state, settings),
            name="pixie-revalidate-all",
        )
    return templates.TemplateResponse(
        request,
        "partials/revalidate_status.html",
        {"request": request, "status": request.app.state.revalidate_status},
    )


@router.get("/settings/revalidate-status", response_class=HTMLResponse)
async def revalidate_status_fragment(
    request: Request,
    templates: TemplatesDep,
) -> HTMLResponse:
    status = getattr(request.app.state, "revalidate_status", None)
    return templates.TemplateResponse(
        request,
        "partials/revalidate_status.html",
        {"request": request, "status": status},
    )


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


@router.post("/settings/clear-history")
async def clear_history(
    request: Request,
    settings: SettingsDep,
) -> Response:
    """Drop run history. Accepts form-encoded OR JSON ``{tool_id}``.

    Omitting ``tool_id`` (or sending ``null``) wipes every tool's runs.
    """

    body = await _read_body(request)
    raw_id = body.get("tool_id")
    tool_id: str | None
    if raw_id is None or raw_id == "":
        tool_id = None
    else:
        tool_id = str(raw_id)
    deleted = await db.delete_runs(settings.db_path, tool_id=tool_id)
    target = tool_id or "all tools"
    return Response(
        status_code=200,
        headers=_toast_header(f"Cleared {deleted} run(s) for {target}."),
    )


@router.post("/settings/vacuum")
async def vacuum_db(settings: SettingsDep) -> Response:
    size = await db.vacuum(settings.db_path)
    kb = max(1, size // 1024)
    return Response(
        status_code=200,
        headers=_toast_header(f"Database vacuumed. Now {kb} KB."),
    )


# ---------------------------------------------------------------------------
# Per-tool settings
# ---------------------------------------------------------------------------


def _tool_view_context(
    request: Request, settings: Settings, persisted: dict[str, Any],
    tool: DiscoveredTool, sidebar: dict[str, Any], overrides: dict[str, Any],
    last_report: dict[str, Any] | None,
) -> dict[str, Any]:
    schema = tool.schema
    assert schema is not None
    declared_secrets = schema.secrets or []
    secrets_rows = pixie_secrets.get_env_status(tool.path, declared_secrets)
    effective = {
        "max_memory_mb": int(
            overrides.get("max_memory_mb") or schema.max_memory_mb
        ),
        "max_runtime_seconds": int(
            overrides.get("max_runtime_seconds") or schema.max_runtime_seconds
        ),
        "warm_keep_seconds": int(
            overrides.get("warm_keep_seconds") or schema.warm_keep_seconds
        ),
        "concurrent": bool(
            overrides.get("concurrent")
            if "concurrent" in overrides
            else schema.concurrent
        ),
    }
    ctx = _base_context(request, settings, persisted)
    ctx.update(
        sidebar_groups=sidebar["sidebar_groups"],
        running_count=sidebar["running_count"],
        active_tool_id=tool.tool_id,
        tool=tool,
        secrets_rows=secrets_rows,
        defaults={
            "max_memory_mb": schema.max_memory_mb,
            "max_runtime_seconds": schema.max_runtime_seconds,
            "warm_keep_seconds": schema.warm_keep_seconds,
            "concurrent": schema.concurrent,
        },
        effective=effective,
        latest_report=last_report,
    )
    return ctx


@router.get("/tool/{tool_id}/settings", response_class=HTMLResponse)
async def tool_settings_page(
    tool_id: str,
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    tool = _resolve_tool(settings, tool_id)
    if tool is None or tool.schema is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    sidebar = await _sidebar_payload(settings, launcher)
    persisted = await load_global_settings(settings)
    overrides = await db.get_tool_overrides(settings.db_path, tool.tool_id)
    last_report = await db.latest_validation_report(settings.db_path, tool.tool_id)
    ctx = _tool_view_context(
        request, settings, persisted, tool, sidebar, overrides, last_report
    )
    template = (
        "partials/tool_settings_body.html"
        if request.headers.get("hx-request", "").lower() == "true"
        else "tool_settings.html"
    )
    return templates.TemplateResponse(request, template, ctx)


@router.post("/tool/{tool_id}/secrets/{key}", response_class=HTMLResponse)
async def set_tool_secret(
    tool_id: str,
    key: str,
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    tool = _resolve_tool(settings, tool_id)
    if tool is None or tool.schema is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    body = await _read_body(request)
    value = str(body.get("value", "") or "")
    if not value:
        return HTMLResponse(
            content="",
            status_code=400,
            headers=_toast_header("Secret value must be non-empty.", "error"),
        )
    pixie_secrets.set_env_value(tool.path, key, value)
    # Restart the warm tool (if any) so it picks up the new env on next call.
    await launcher.stop(tool.tool_id)
    row = _find_secret_row(tool, key)
    response = templates.TemplateResponse(
        request, "partials/secret_row.html",
        {"request": request, "row": row, "tool": tool},
    )
    response.headers.update(_toast_header(f"Saved {key}."))
    return response


@router.delete("/tool/{tool_id}/secrets/{key}", response_class=HTMLResponse)
async def delete_tool_secret(
    tool_id: str,
    key: str,
    request: Request,
    settings: SettingsDep,
    launcher: LauncherDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    tool = _resolve_tool(settings, tool_id)
    if tool is None or tool.schema is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    pixie_secrets.clear_env_value(tool.path, key)
    await launcher.stop(tool.tool_id)
    row = _find_secret_row(tool, key)
    response = templates.TemplateResponse(
        request, "partials/secret_row.html",
        {"request": request, "row": row, "tool": tool},
    )
    response.headers.update(_toast_header(f"Cleared {key}."))
    return response


def _find_secret_row(tool: DiscoveredTool, key: str) -> dict[str, Any]:
    schema = tool.schema
    assert schema is not None
    rows = pixie_secrets.get_env_status(tool.path, schema.secrets or [])
    for row in rows:
        if row["key"] == key:
            return row
    # Secret no longer declared but still exists — surface it generically.
    present = pixie_secrets.read_env(tool.path)
    return {
        "key": key,
        "description": None,
        "required": False,
        "status": "set" if present.get(key) else "not_set",
    }


@router.post("/tool/{tool_id}/overrides", response_class=HTMLResponse)
async def save_tool_overrides(
    tool_id: str,
    request: Request,
    settings: SettingsDep,
) -> Response:
    tool = _resolve_tool(settings, tool_id)
    if tool is None or tool.schema is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    schema = tool.schema
    body = await _read_body(request)

    def _as_int(field: str, default: int = 0) -> int:
        raw = body.get(field, default)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"{field} must be an integer"
            ) from exc

    max_memory_mb = _as_int("max_memory_mb")
    max_runtime_seconds = _as_int("max_runtime_seconds")
    warm_keep_seconds = _as_int("warm_keep_seconds")
    concurrent_raw = body.get("concurrent", "")
    if isinstance(concurrent_raw, bool):
        concurrent_flag = concurrent_raw
    else:
        concurrent_flag = str(concurrent_raw).strip().lower() in (
            "1", "true", "on", "yes"
        )

    overrides: dict[str, Any] = {}
    if max_memory_mb and max_memory_mb != schema.max_memory_mb:
        overrides["max_memory_mb"] = max(64, min(int(max_memory_mb), 65536))
    if max_runtime_seconds and max_runtime_seconds != schema.max_runtime_seconds:
        overrides["max_runtime_seconds"] = max(
            1, min(int(max_runtime_seconds), 24 * 3600)
        )
    if warm_keep_seconds and warm_keep_seconds != schema.warm_keep_seconds:
        overrides["warm_keep_seconds"] = max(
            0, min(int(warm_keep_seconds), 24 * 3600)
        )
    if concurrent_flag != schema.concurrent:
        overrides["concurrent"] = concurrent_flag
    await db.set_tool_overrides(settings.db_path, tool.tool_id, overrides)
    return Response(
        status_code=200,
        headers=_toast_header("Overrides saved."),
    )


@router.post("/tool/{tool_id}/validate-now", response_class=HTMLResponse)
async def validate_tool_now(
    tool_id: str,
    request: Request,
    settings: SettingsDep,
    templates: TemplatesDep,
) -> HTMLResponse:
    tool = _resolve_tool(settings, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    report = await validate_tool(tool.path, save_to_db=True)
    payload = json.loads(report.model_dump_json())
    overall = payload.get("overall", "unknown")
    toast_kind = "success" if overall == "pass" else (
        "warn" if overall == "warn" else "error"
    )
    return templates.TemplateResponse(
        request, "partials/validation_panel.html",
        {"request": request, "report": payload, "tool_id": tool.tool_id},
        headers=_toast_header(f"Validation complete: {overall}.", toast_kind),
    )


@router.post("/tool/{tool_id}/open-folder")
async def open_tool_folder(
    tool_id: str,
    settings: SettingsDep,
) -> Response:
    tool = _resolve_tool(settings, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    try:
        _reveal_in_file_browser(str(tool.path))
    except OSError as exc:
        return Response(
            status_code=500,
            headers=_toast_header(f"Could not open folder: {exc}", "error"),
        )
    return Response(
        status_code=200,
        headers=_toast_header(f"Opened {tool.path.name} in file browser."),
    )


def _reveal_in_file_browser(path: str) -> None:
    """Open the host platform's file browser at ``path``.

    Delegates to :func:`pixie.cli_helpers.open_in_os` so the HTTP layer
    and the ``pixie open`` CLI command share one implementation.
    """

    from pixie.cli_helpers import open_in_os

    open_in_os(Path(path))


@router.post("/tool/{tool_id}/hot-reload")
async def hot_reload_tool(
    tool_id: str,
    settings: SettingsDep,
    launcher: LauncherDep,
) -> Response:
    tool = _resolve_tool(settings, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id!r} not found")
    was_running = launcher.is_running(tool.tool_id)
    await launcher.stop(tool.tool_id)
    msg = (
        f"Stopped warm process for {tool.tool_id}."
        if was_running
        else f"{tool.tool_id} was not warm — nothing to reload."
    )
    return Response(status_code=200, headers=_toast_header(msg))


__all__ = [
    "router",
    "load_global_settings",
    "GLOBAL_KEYS",
    "ACCENT_CHOICES",
    "DENSITY_CHOICES",
    "THEME_CHOICES",
]
