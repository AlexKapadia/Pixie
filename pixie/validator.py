"""End-to-end tool validator.

Runs twelve deterministic checks against a tool folder, in fixed order,
producing a ``ValidationReport``. Used by:

* the CLI (``pixie validate <tool_id>``)
* the HTTP API (``GET /api/tools/{id}/validate``)
* the discovery step at startup (cached)
* every skill that creates or modifies a tool

Check #12 ``reference_fixtures_match`` (RESEARCH_reference_validator.md)
runs every ``reference/fixture_*.json`` against the live warm-spawn
process, comparing outputs through the per-type comparator package.
Tools without a ``reference/`` folder simply ``skip`` that check.

The validator is read-only: it never modifies the tool, never runs
``uv sync``. If ``.venv`` is missing, that is a fail and the report
explains it. Spawn uses the same isolated subprocess pattern as the
launcher (loopback only, scrubbed env, captured stderr).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from packaging.requirements import InvalidRequirement, Requirement
from pydantic import BaseModel, ValidationError

from pixie import db
from pixie.comparators import (
    FixtureResult,
    ReferenceFixture,
    ToleranceConfig,
    deep_compare,
    format_diff_report,
    format_skip_report,
    list_reference_fixtures,
    load_fixtures,
    load_tolerance_yaml,
)
from pixie.config import get_settings
from pixie.discovery import ToolSchema, load_tool_schema  # noqa: F401  (re-exported)
from pixie.launcher import (
    HEALTHZ_INTERVAL_S,
    HEALTHZ_TIMEOUT_S,
    StderrRing,
    _build_child_env,
    _free_port,
    _popen_kwargs,
    _pump_stderr,
    _send_graceful,
    _send_hard,
    _venv_python,
)

logger = logging.getLogger("pixie.validator")

REQUIRED_FILES = ("tool.json", "pyproject.toml", "main.py")
REQUIRED_DEPS = ("fastapi", "uvicorn", "pydantic", "python-dotenv")
SHUTDOWN_GRACE_S = 5.0
SAMPLE_RUN_PADDING_S = 5.0
STREAM_TIMEOUT_S = 10.0

_PNG_1X1_TRANSPARENT_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhg"
    "GAWjR9awAAAABJRU5ErkJggg=="
)


# --- report models -----------------------------------------------------------


class ValidationCheck(BaseModel):
    name: str
    status: Literal["pass", "fail", "warn", "skip"]
    message: str
    details: str | None = None


class ValidationReport(BaseModel):
    tool_id: str
    tool_path: str
    timestamp: datetime
    overall: Literal["pass", "fail", "warn"]
    checks: list[ValidationCheck]
    sample_inputs: dict[str, Any] | None = None
    sample_output: dict[str, Any] | None = None
    spawn_log: str | None = None
    # Auxiliary, non-core warnings. NOT part of the 12 deterministic checks
    # and does NOT influence ``overall``. Currently populated by the kill-file
    # cross-reference (see ``_check_kill_file_unaddressed``).
    warnings: list[str] = []


def summary_report(report: "ValidationReport | dict[str, Any]") -> dict[str, Any]:
    """Return a token-efficient summary of a validation report.

    Skill consumers don't need passing-check noise; only the failed and
    warning checks matter when deciding whether to surface a problem.
    The summary keeps the overall verdict, the tool id, the timestamp,
    counts per status, and only the checks whose status is ``fail`` or
    ``warn`` (with their full message + details).
    """

    if isinstance(report, ValidationReport):
        payload = json.loads(report.model_dump_json())
    else:
        payload = dict(report)

    checks_in = payload.get("checks", []) or []
    counts: dict[str, int] = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    notable: list[dict[str, Any]] = []
    for check in checks_in:
        status = check.get("status", "?")
        counts[status] = counts.get(status, 0) + 1
        if status in {"fail", "warn"}:
            notable.append({
                "name": check.get("name"),
                "status": status,
                "message": check.get("message"),
                "details": check.get("details"),
            })

    return {
        "tool_id": payload.get("tool_id"),
        "tool_path": payload.get("tool_path"),
        "timestamp": payload.get("timestamp"),
        "overall": payload.get("overall"),
        "counts": counts,
        "notable_checks": notable,
        "spawn_log": payload.get("spawn_log"),
        "warnings": payload.get("warnings", []),
    }


# --- sample input generation -------------------------------------------------


_INPUT_DEFAULTS: dict[str, Any] = {
    "text": "",
    "textarea": "",
    "checkbox": False,
    "toggle": False,
    "date": "2026-01-01",
    "time": "12:00",
    "datetime": "2026-01-01T12:00:00",
    "date_range": ["2026-01-01", "2026-01-08"],
    "colour": "#000000",
    "json": {},
    "code": "",
    "markdown": "",
    "tags": [],
    "autocomplete": "",
    "multiselect": [],
    "hidden": None,
}


def _sample_for_input(spec: Any) -> Any:
    """Pick a representative value for one input spec.

    Prefers the spec's declared ``default`` when present; otherwise falls
    back to type-appropriate values per ARCHITECTURE.md s8.
    """

    spec_type = getattr(spec, "type", None)
    default = getattr(spec, "default", None)
    if default is not None:
        return default

    if spec_type in _INPUT_DEFAULTS:
        return _INPUT_DEFAULTS[spec_type]

    if spec_type == "number":
        min_v = getattr(spec, "min", None)
        max_v = getattr(spec, "max", None)
        if min_v is not None and max_v is not None:
            return (min_v + max_v) / 2.0
        if min_v is not None:
            return float(min_v)
        return 0
    if spec_type == "slider":
        min_v = float(getattr(spec, "min"))
        max_v = float(getattr(spec, "max"))
        midpoint = (min_v + max_v) / 2.0
        if getattr(spec, "range", False):
            return [min_v, midpoint]
        return midpoint
    if spec_type in {"select", "radio"}:
        options = getattr(spec, "options", []) or []
        if options:
            return options[0].value
        return None
    if spec_type == "table":
        return []
    if spec_type in {"image", "file", "audio"}:
        return f"data:image/png;base64,{_PNG_1X1_TRANSPARENT_B64}"
    if spec_type in {"map_point", "map_bbox", "map_polygon", "map_multipoint"}:
        centre = getattr(spec, "default_center", None) or [0.0, 0.0]
        if spec_type == "map_point":
            return list(centre)
        if spec_type == "map_bbox":
            return [centre[0] - 0.01, centre[1] - 0.01, centre[0] + 0.01, centre[1] + 0.01]
        return [list(centre)]
    return None


def generate_sample_inputs(schema: ToolSchema) -> dict[str, Any]:
    """Build a complete sample-inputs dict for a tool.

    For chat-layout tools (``layout == "chat"``) the inputs branch returns
    the canonical chat probe shape ``{messages: [{role, content}], history: []}``
    instead of walking the declared input specs. Form/split layouts use the
    per-spec defaults via :func:`_sample_for_input`.
    """

    if schema.layout == "chat":
        return {
            "messages": [
                {"role": "user", "content": "Validation probe message"}
            ],
            "history": [],
        }
    return {spec.key: _sample_for_input(spec) for spec in schema.inputs}


def build_sample_run_payload(schema: ToolSchema) -> dict[str, Any]:
    """Wrap the sample inputs in the ``{run_id, inputs}`` body shape.

    Per DECISIONS s tool-patterns item 1, every ``/run`` call carries a
    fresh ``run_id`` UUID alongside the inputs payload. Tools that ignore
    the wrapper still work — they receive their declared input keys at
    the top level via the inputs dict, AND under ``inputs.<key>``.
    """

    inputs = generate_sample_inputs(schema)
    payload: dict[str, Any] = {"run_id": str(uuid.uuid4()), "inputs": inputs}
    # Backward-compatible shim: include the per-key fields at the top level
    # so tools that pre-date the wrapped shape still receive their inputs.
    for key, value in inputs.items():
        if key not in payload:
            payload[key] = value
    return payload


# --- output conformance ------------------------------------------------------


_OUTPUT_OBJECT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "table": ("columns", "rows"),
    "kv": ("pairs",),
    "chart_line": ("x", "series"),
    "chart_bar": ("x", "series"),
    "chart_area": ("x", "series"),
    "chart_scatter": ("series",),
    "chart_pie": ("slices",),
    "chart_histogram": ("values",),
    "chart_boxplot": ("series",),
    "chart_heatmap": ("z",),
    "chart_candlestick": ("points",),
    "chart_radar": ("axes", "series"),
    "chart_sankey": ("nodes", "links"),
    "chart_treemap": ("nodes",),
    "chart_network": ("nodes", "edges"),
    "map_points": ("points",),
    "map_heatmap": ("points",),
    "map_choropleth": ("geojson", "values"),
    "map_polygons": ("polygons",),
    "map_route": ("points",),
    "image_grid": ("images",),
    "image_compare": ("before", "after"),
    "diff": ("before", "after"),
    "tree": ("root",),
    "timeline": ("events",),
    "gantt": ("tasks",),
    "log": ("lines",),
    "file": ("filename", "data"),
}

_SCALAR_OUTPUTS = {
    "text", "markdown", "number", "boolean", "image", "audio",
    "video", "latex", "code", "stream_text", "progress",
}


def _check_output_value(spec: Any, value: Any) -> tuple[str, str | None]:
    """Return ("pass"|"fail", error_msg_or_None) for a single declared output."""

    output_type = getattr(spec, "type")
    if value is None:
        return "fail", f"output {spec.key!r}: value is null"

    if output_type in _SCALAR_OUTPUTS:
        # Tolerant: accept either a wrapped object {value: ...} or a raw scalar.
        if isinstance(value, dict) and "value" in value:
            return "pass", None
        if output_type in {"text", "markdown", "code", "latex", "stream_text"}:
            return ("pass", None) if isinstance(value, str) else (
                "fail",
                f"output {spec.key!r}: expected string, got {type(value).__name__}",
            )
        if output_type == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            return ("pass", None) if ok else (
                "fail",
                f"output {spec.key!r}: expected number, got {type(value).__name__}",
            )
        if output_type == "boolean":
            ok = isinstance(value, bool) or (isinstance(value, int) and value in (0, 1))
            return ("pass", None) if ok else (
                "fail",
                f"output {spec.key!r}: expected bool, got {type(value).__name__}",
            )
        if output_type == "progress":
            ok = value is None or isinstance(value, (int, float))
            return ("pass", None) if ok else (
                "fail",
                f"output {spec.key!r}: progress must be number or null",
            )
        # image/audio/video: a string URL or data URL.
        return ("pass", None) if isinstance(value, str) else (
            "fail",
            f"output {spec.key!r}: expected string url/data-url",
        )

    required = _OUTPUT_OBJECT_REQUIREMENTS.get(output_type, ())
    if not required:
        return "pass", None
    if not isinstance(value, dict):
        return "fail", f"output {spec.key!r}: expected object, got {type(value).__name__}"
    missing = [key for key in required if key not in value]
    if missing:
        return "fail", f"output {spec.key!r}: missing fields {missing}"
    return "pass", None


# --- pyproject parsing -------------------------------------------------------


def _canonical_dep_name(name: str) -> str:
    """PEP 503 canonical normalisation: lowercase + collapse [-_.]+ to '-'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _extract_dep_names(deps: list[str]) -> list[str]:
    """Parse each dependency string via packaging.requirements.Requirement.

    Falls back to a permissive substring split only when the spec is not
    parseable as a PEP 508 requirement (e.g. local file paths). Returned
    names are PEP 503 canonical (lowercase, '-' separator) so they can be
    compared directly against REQUIRED_DEPS.
    """
    names: list[str] = []
    for dep in deps:
        spec = dep.strip()
        if not spec:
            continue
        try:
            requirement = Requirement(spec)
            names.append(_canonical_dep_name(requirement.name))
            continue
        except InvalidRequirement:
            pass
        # Fallback: best-effort split for non-PEP-508 specs.
        token = spec.split(";", 1)[0].strip()
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " ", "@"):
            if separator in token:
                token = token.split(separator, 1)[0]
                break
        names.append(_canonical_dep_name(token.strip()))
    return names


def _looks_like_non_pypi(dep: str) -> bool:
    lowered = dep.lower().strip()
    if any(prefix in lowered for prefix in ("git+", "url=", "file://", "@ http")):
        return True
    name_part = lowered.split(";", 1)[0].split("[", 1)[0].split("==", 1)[0].strip()
    return name_part.startswith(("./", "../", "/", ".\\", "..\\")) or name_part.endswith(
        (".whl", ".tar.gz", ".zip")
    )


# --- individual checks -------------------------------------------------------


async def _check_folder_structure(tool_path: Path) -> ValidationCheck:
    missing = [name for name in REQUIRED_FILES if not (tool_path / name).is_file()]
    if missing:
        return ValidationCheck(
            name="folder_structure", status="fail",
            message=f"missing required files: {', '.join(missing)}",
        )
    unreadable: list[str] = []
    for name in REQUIRED_FILES:
        try:
            (tool_path / name).read_bytes()
        except OSError as exc:
            unreadable.append(f"{name}: {exc}")
    if unreadable:
        return ValidationCheck(
            name="folder_structure", status="fail",
            message="some required files are not readable",
            details="\n".join(unreadable),
        )
    return ValidationCheck(
        name="folder_structure", status="pass",
        message="tool.json, pyproject.toml, and main.py present and readable",
    )


async def _check_tool_json_parses(tool_path: Path) -> tuple[ValidationCheck, ToolSchema | None]:
    path = tool_path / "tool.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationCheck(
            name="tool_json_parses", status="fail",
            message=f"could not read tool.json: {exc}",
        ), None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ValidationCheck(
            name="tool_json_parses", status="fail",
            message=f"tool.json is not valid JSON: {exc}",
            details=raw[:2_000],
        ), None
    try:
        schema = ToolSchema.model_validate(data)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            problems.append(f"  {location}: {error.get('msg')}")
        return ValidationCheck(
            name="tool_json_parses", status="fail",
            message=f"tool.json failed schema validation ({len(exc.errors())} issue(s))",
            details="\n".join(problems),
        ), None
    return ValidationCheck(
        name="tool_json_parses", status="pass",
        message=f"tool.json parsed as ToolSchema (id={schema.id!r})",
    ), schema


async def _check_schemas_coherent(schema: ToolSchema) -> ValidationCheck:
    problems: list[str] = []

    seen: set[str] = set()
    input_keys: list[str] = []
    for spec in schema.inputs:
        if spec.key in seen:
            problems.append(f"duplicate input key: {spec.key!r}")
        seen.add(spec.key)
        input_keys.append(spec.key)

    seen = set()
    output_keys: list[str] = []
    for spec in schema.outputs:
        if spec.key in seen:
            problems.append(f"duplicate output key: {spec.key!r}")
        seen.add(spec.key)
        output_keys.append(spec.key)

    input_key_set = set(input_keys)
    for spec in schema.inputs:
        condition = getattr(spec, "show_if", None)
        if condition is not None and condition.key not in input_key_set:
            problems.append(
                f"input {spec.key!r}: show_if references missing key {condition.key!r}"
            )

    if problems:
        return ValidationCheck(
            name="schemas_coherent", status="fail",
            message=f"{len(problems)} schema coherence issue(s)",
            details="\n".join(problems),
        )
    return ValidationCheck(
        name="schemas_coherent", status="pass",
        message=(
            f"{len(input_keys)} input(s), {len(output_keys)} output(s); "
            "keys unique; show_if references valid"
        ),
    )


async def _check_pyproject(tool_path: Path) -> ValidationCheck:
    path = tool_path / "pyproject.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return ValidationCheck(
            name="pyproject_ok", status="fail",
            message=f"pyproject.toml could not be parsed: {exc}",
        )
    project = data.get("project", {})
    deps_raw = project.get("dependencies", []) or []
    dep_names = _extract_dep_names(deps_raw)
    declared_set = set(dep_names)
    per_dep_status = [
        f"  {name}: {'present' if name in declared_set else 'MISSING'}"
        for name in REQUIRED_DEPS
    ]
    missing = [name for name in REQUIRED_DEPS if name not in declared_set]
    if missing:
        return ValidationCheck(
            name="pyproject_ok", status="fail",
            message=f"missing required dependencies: {', '.join(missing)}",
            details=(
                "required canonical names (PEP 503):\n"
                + "\n".join(per_dep_status)
                + f"\ndeclared (canonicalised): {dep_names}"
            ),
        )
    non_pypi = [dep for dep in deps_raw if _looks_like_non_pypi(dep)]
    if non_pypi:
        return ValidationCheck(
            name="pyproject_ok", status="warn",
            message="non-PyPI dependency entries detected",
            details="\n".join(non_pypi),
        )
    return ValidationCheck(
        name="pyproject_ok", status="pass",
        message=f"pyproject.toml parses; required deps present ({len(dep_names)} total)",
    )


async def _check_venv(tool_path: Path) -> ValidationCheck:
    python = _venv_python(tool_path)
    if not python.exists():
        return ValidationCheck(
            name="venv_exists", status="fail",
            message=f"venv interpreter missing at {python}",
            details=(
                "Run `uv sync` in the tool folder. "
                "The validator never installs dependencies."
            ),
        )
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [str(python), "--version"],
            capture_output=True, text=True, timeout=5.0,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return ValidationCheck(
            name="venv_exists", status="fail",
            message=f"venv interpreter failed to run: {exc}",
        )
    if result.returncode != 0:
        return ValidationCheck(
            name="venv_exists", status="fail",
            message=f"`python --version` returned {result.returncode}",
            details=(result.stdout + result.stderr).strip()[:1_000],
        )
    return ValidationCheck(
        name="venv_exists", status="pass",
        message=(result.stdout or result.stderr).strip(),
    )


# --- subprocess helpers (validator-local, reusing launcher primitives) -------


async def _spawn_for_validation(
    tool_path: Path, schema: ToolSchema, port: int
) -> tuple[asyncio.subprocess.Process, StderrRing, asyncio.Task[None]]:
    """One-shot spawn for the validator (no warm-keep, no registry).

    Mirrors :meth:`Launcher._spawn` but isolated. Reuses launcher helpers
    so spawn semantics are identical. Sets ``PIXIE_VALIDATE=true`` so
    tools that respect the convention (DECISIONS s tool-patterns item 6)
    can skip slow LLM calls during validation.
    """

    python = _venv_python(tool_path)
    env = _build_child_env(tool_path)
    env["PIXIE_VALIDATE"] = "true"
    spawn_time = asyncio.get_running_loop().time()
    process = await asyncio.create_subprocess_exec(
        str(python), schema.entrypoint, "--port", str(port),
        cwd=str(tool_path),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        **_popen_kwargs(schema),
    )
    # Stash spawn timestamp on the process object so _poll_healthz can
    # detect the "clean exit during startup" pattern (signals a missing
    # __main__ guard in main.py).
    setattr(process, "_pixie_spawn_time", spawn_time)
    ring = StderrRing()
    pump = asyncio.create_task(_pump_stderr(process, ring))
    return process, ring, pump


async def _poll_healthz(
    client: httpx.AsyncClient,
    process: asyncio.subprocess.Process,
    ring: StderrRing,
    port: int,
) -> tuple[bool, str]:
    deadline = asyncio.get_running_loop().time() + HEALTHZ_TIMEOUT_S
    url = f"http://127.0.0.1:{port}/healthz"
    while True:
        if process.returncode is not None:
            stderr_snapshot = ring.snapshot()
            detail = (
                f"process exited with code {process.returncode} during startup\n"
                f"--- stderr ---\n{stderr_snapshot}"
            )
            spawn_time = getattr(process, "_pixie_spawn_time", None)
            elapsed = (
                asyncio.get_running_loop().time() - spawn_time
                if spawn_time is not None else None
            )
            # "Clean exit during startup" pattern: exit 0, no stderr,
            # under 2 s since spawn. Almost always a missing
            # `if __name__ == "__main__": main()` block — Python parses
            # main.py, defines main() but never calls it, then exits.
            if (
                process.returncode == 0
                and not stderr_snapshot.strip()
                and elapsed is not None
                and elapsed < 2.0
            ):
                detail += (
                    "\nprocess exited cleanly during startup — main.py likely "
                    "missing 'if __name__ == \"__main__\"' block; see "
                    "pixie/templates_scaffold/blank/main.py for the required runner"
                )
            return False, detail
        try:
            response = await client.get(url, timeout=1.0)
            if response.status_code == 200:
                return True, ""
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError,
                httpx.ConnectTimeout, httpx.ReadTimeout):
            pass
        if asyncio.get_running_loop().time() > deadline:
            return False, (
                f"/healthz did not return 200 within {HEALTHZ_TIMEOUT_S}s\n"
                f"--- stderr ---\n{ring.snapshot()}"
            )
        await asyncio.sleep(HEALTHZ_INTERVAL_S)


async def _terminate_for_validation(
    process: asyncio.subprocess.Process,
    pump: asyncio.Task[None],
    grace: float = SHUTDOWN_GRACE_S,
) -> tuple[bool, int | None]:
    clean = True
    if process.returncode is None:
        _send_graceful(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=grace)
        except asyncio.TimeoutError:
            clean = False
            _send_hard(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
    if not pump.done():
        pump.cancel()
        try:
            await pump
        except (asyncio.CancelledError, Exception):
            pass
    return clean, process.returncode


# --- canonicalisation for schema-drift diff ----------------------------------


_MISSING = object()


def _canonicalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonicalise(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonicalise(v) for v in value]
    return value


def _diff_schemas(disk: dict[str, Any], live: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    disk_canonical = _canonicalise(disk)
    live_canonical = _canonicalise(live)
    diffs: list[tuple[str, Any, Any]] = []

    def walk(path: str, a: Any, b: Any) -> None:
        if a is _MISSING or b is _MISSING:
            diffs.append((path or "/", a, b))
            return
        if type(a) is not type(b):
            diffs.append((path or "/", a, b))
            return
        if isinstance(a, dict):
            for key in sorted(set(a) | set(b)):
                walk(f"{path}/{key}", a.get(key, _MISSING), b.get(key, _MISSING))
        elif isinstance(a, list):
            if len(a) != len(b):
                diffs.append((path or "/", a, b))
                return
            for i, (av, bv) in enumerate(zip(a, b)):
                walk(f"{path}/{i}", av, bv)
        elif a != b:
            diffs.append((path or "/", a, b))

    walk("", disk_canonical, live_canonical)
    return diffs


# --- streaming check ---------------------------------------------------------


async def _check_streaming(
    client: httpx.AsyncClient,
    sample_output: dict[str, Any] | None,
    port: int,
) -> ValidationCheck:
    run_id = "validator"
    if isinstance(sample_output, dict):
        candidate = sample_output.get("run_id") or sample_output.get("id")
        if isinstance(candidate, str):
            run_id = candidate
    url = f"http://127.0.0.1:{port}/stream"
    try:
        async with client.stream(
            "GET", url, params={"run_id": run_id}, timeout=STREAM_TIMEOUT_S,
        ) as response:
            if response.status_code != 200:
                return ValidationCheck(
                    name="streaming_check", status="fail",
                    message=f"GET /stream returned HTTP {response.status_code}",
                )
            try:
                async for chunk in response.aiter_bytes():
                    if chunk:
                        return ValidationCheck(
                            name="streaming_check", status="pass",
                            message="received at least one SSE event",
                        )
            except httpx.ReadTimeout:
                return ValidationCheck(
                    name="streaming_check", status="fail",
                    message=f"no SSE events received within {STREAM_TIMEOUT_S:.0f}s",
                )
        return ValidationCheck(
            name="streaming_check", status="fail",
            message="/stream closed without sending any events",
        )
    except httpx.HTTPError as exc:
        return ValidationCheck(
            name="streaming_check", status="fail",
            message=f"could not open SSE stream: {exc}",
        )


# --- check #12: reference fixtures -------------------------------------------


REFERENCE_CHECK_OVERALL_BUDGET_S = 60.0
REFERENCE_PER_FIXTURE_DEFAULT_S = 30.0


async def _check_reference_fixtures(
    tool_path: Path,
    schema: ToolSchema,
    client: httpx.AsyncClient,
    port: int,
    fixture_filter: list[str] | None = None,
    tag_filter: list[str] | None = None,
) -> tuple[ValidationCheck, list[FixtureResult], dict[str, Any] | None, dict[str, Any] | None]:
    """Run check #12 against the warm-spawned process.

    Returns ``(check, fixture_results, first_fail_inputs, first_fail_outputs)``
    so the orchestrator can surface inputs / outputs on the report for the
    first failing fixture (useful in the UI).
    """

    reference_dir = tool_path / "reference"
    if not reference_dir.is_dir():
        return ValidationCheck(
            name="reference_fixtures_match", status="skip",
            message="no reference/ folder; check skipped",
        ), [], None, None

    fixture_paths = sorted(reference_dir.glob("fixture_*.json"))
    if fixture_filter:
        wanted = set()
        for token in fixture_filter:
            wanted.add(token)
            wanted.add(token if token.startswith("fixture_") else f"fixture_{token}")
            for path in reference_dir.glob(token):
                wanted.add(path.name)
        fixture_paths = [
            path for path in fixture_paths
            if path.name in wanted
            or path.stem in wanted
            or path.stem.removeprefix("fixture_") in wanted
        ]

    if not fixture_paths:
        msg = "reference/ has no fixture_*.json files"
        if fixture_filter:
            msg = f"no fixtures matched {fixture_filter!r}"
        return ValidationCheck(
            name="reference_fixtures_match", status="skip",
            message=msg,
        ), [], None, None

    tolerance = load_tolerance_yaml(reference_dir / "tolerance.yaml")
    if tolerance.errors:
        return ValidationCheck(
            name="reference_fixtures_match", status="fail",
            message=f"invalid tolerance.yaml ({len(tolerance.errors)} issue(s))",
            details="\n".join(tolerance.errors),
        ), [], None, None

    declared_output_keys = {spec.key for spec in schema.outputs}
    fixtures, load_errors = load_fixtures(
        fixture_paths,
        declared_input_keys={spec.key for spec in schema.inputs},
        declared_output_keys=declared_output_keys,
    )
    if load_errors:
        return ValidationCheck(
            name="reference_fixtures_match", status="fail",
            message=f"could not load {len(load_errors)} fixture(s)",
            details="\n".join(load_errors),
        ), [], None, None

    if tag_filter:
        wanted_tags = set(tag_filter)
        fixtures = [
            f for f in fixtures
            if any(tag in wanted_tags for tag in (f.tags or []))
        ]
        if not fixtures:
            return ValidationCheck(
                name="reference_fixtures_match", status="skip",
                message=f"no fixtures matched tag(s) {sorted(wanted_tags)}",
            ), [], None, None

    overall_budget = (
        schema.validator_timeout_override
        if schema.validator_timeout_override is not None
        else REFERENCE_CHECK_OVERALL_BUDGET_S
    )
    deadline = asyncio.get_running_loop().time() + float(overall_budget)
    fixture_results: list[FixtureResult] = []
    first_fail_inputs: dict[str, Any] | None = None
    first_fail_outputs: dict[str, Any] | None = None

    for fixture in fixtures:
        if fixture.skip_reason:
            fixture_results.append(FixtureResult(
                name=fixture.name, status="skip",
                message=fixture.skip_reason, source=fixture.source,
            ))
            continue

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            fixture_results.append(FixtureResult(
                name=fixture.name, status="fail",
                message="overall budget exhausted before this fixture ran",
                source=fixture.source,
            ))
            continue

        per_fixture_cap = (
            fixture.validator_timeout_override
            if fixture.validator_timeout_override is not None
            else (
                float(schema.validator_timeout_override)
                if schema.validator_timeout_override is not None
                else schema.max_runtime_seconds + SAMPLE_RUN_PADDING_S
            )
        )
        per_run_timeout = min(per_fixture_cap, max(remaining, 0.1))

        payload = {"run_id": str(uuid.uuid4()), "inputs": fixture.inputs}
        try:
            response = await client.post(
                f"http://127.0.0.1:{port}/run",
                json=payload, timeout=per_run_timeout,
            )
            response.raise_for_status()
            actual_outputs = response.json()
        except httpx.HTTPError as exc:
            fixture_results.append(FixtureResult(
                name=fixture.name, status="fail",
                message=f"/run raised {type(exc).__name__}: {exc}",
                source=fixture.source,
            ))
            if first_fail_inputs is None:
                first_fail_inputs = fixture.inputs
            continue
        except json.JSONDecodeError as exc:
            fixture_results.append(FixtureResult(
                name=fixture.name, status="fail",
                message=f"/run response was not JSON: {exc}",
                source=fixture.source,
            ))
            if first_fail_inputs is None:
                first_fail_inputs = fixture.inputs
            continue

        diffs = deep_compare(
            expected_outputs=fixture.expected_outputs,
            actual_outputs=actual_outputs,
            output_specs=schema.outputs,
            tolerance_config=tolerance,
            fixture_overrides=fixture.tolerance,
        )
        if diffs:
            fixture_results.append(FixtureResult(
                name=fixture.name, status="fail",
                message=f"{len(diffs)} output(s) differ",
                diffs=diffs, source=fixture.source,
            ))
            if first_fail_inputs is None:
                first_fail_inputs = fixture.inputs
                first_fail_outputs = actual_outputs if isinstance(actual_outputs, dict) else None
        else:
            fixture_results.append(FixtureResult(
                name=fixture.name, status="pass",
                message="all declared outputs matched",
                source=fixture.source,
            ))

    check = _summarise_reference_results(fixture_results)
    return check, fixture_results, first_fail_inputs, first_fail_outputs


def _summarise_reference_results(results: list[FixtureResult]) -> ValidationCheck:
    failed = [r for r in results if r.status == "fail"]
    skipped = [r for r in results if r.status == "skip"]
    passed = [r for r in results if r.status == "pass"]

    if failed:
        return ValidationCheck(
            name="reference_fixtures_match", status="fail",
            message=(
                f"{len(failed)} of {len(results)} fixture(s) failed "
                f"({len(passed)} passed, {len(skipped)} skipped)"
            ),
            details=format_diff_report(failed),
        )
    if not passed and skipped:
        return ValidationCheck(
            name="reference_fixtures_match", status="warn",
            message=f"all {len(skipped)} fixture(s) skipped",
            details=format_skip_report(skipped),
        )
    return ValidationCheck(
        name="reference_fixtures_match", status="pass",
        message=(
            f"{len(passed)} fixture(s) matched"
            + (f"; {len(skipped)} skipped" if skipped else "")
        ),
    )


async def update_reference_fixtures(
    tool_path: Path,
    *,
    fixture_filter: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Re-run each fixture's inputs and rewrite its ``expected_outputs``.

    Returns a structured report:
    ``{"would_update": [...], "updated": [...], "errors": [...]}``.

    With ``dry_run=True`` (the default) no file is written; the caller
    must explicitly pass ``dry_run=False`` (CLI ``--yes``) to commit.
    """

    from datetime import datetime as _dt

    reference_dir = tool_path / "reference"
    result: dict[str, Any] = {
        "would_update": [],
        "updated": [],
        "errors": [],
        "skipped": [],
        "dry_run": dry_run,
    }
    if not reference_dir.is_dir():
        result["errors"].append(f"no reference/ folder at {reference_dir}")
        return result

    schema = load_tool_schema(tool_path)
    fixture_paths = sorted(reference_dir.glob("fixture_*.json"))
    if fixture_filter:
        wanted = set(fixture_filter) | {f"fixture_{f}" for f in fixture_filter}
        fixture_paths = [
            p for p in fixture_paths if p.name in wanted or p.stem in wanted
        ]

    if not fixture_paths:
        result["errors"].append("no matching fixture_*.json files")
        return result

    port = _free_port()
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=2.0)) as client:
        process, ring, pump = await _spawn_for_validation(tool_path, schema, port)
        try:
            ok, err = await _poll_healthz(client, process, ring, port)
            if not ok:
                result["errors"].append(f"tool did not become healthy: {err}")
                return result

            for path in fixture_paths:
                try:
                    fixture_data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    result["errors"].append(f"{path.name}: could not read/parse: {exc}")
                    continue
                inputs = fixture_data.get("inputs") or {}
                payload = {"run_id": str(uuid.uuid4()), "inputs": inputs}
                try:
                    response = await client.post(
                        f"http://127.0.0.1:{port}/run",
                        json=payload, timeout=60.0,
                    )
                    response.raise_for_status()
                    actual = response.json()
                except (httpx.HTTPError, json.JSONDecodeError) as exc:
                    result["errors"].append(
                        f"{path.name}: /run failed: {type(exc).__name__}: {exc}"
                    )
                    continue
                old_expected = fixture_data.get("expected_outputs") or {}
                if old_expected == actual:
                    result["skipped"].append({
                        "file": path.name,
                        "reason": "expected_outputs already match actual",
                    })
                    continue
                if dry_run:
                    result["would_update"].append({
                        "file": path.name,
                        "delta_keys": sorted(set(old_expected) ^ set(actual)) or sorted(actual),
                    })
                    continue
                fixture_data["expected_outputs"] = actual
                source = (
                    f"--update-fixtures at {_dt.now(timezone.utc).isoformat()}"
                )
                if fixture_data.get("source"):
                    fixture_data["source"] = (
                        f"{fixture_data['source']} | refreshed via {source}"
                    )
                else:
                    fixture_data["source"] = source
                path.write_text(
                    json.dumps(fixture_data, indent=2, default=str),
                    encoding="utf-8",
                )
                result["updated"].append(path.name)
        finally:
            await _terminate_for_validation(process, pump)

    return result


# --- finalisation ------------------------------------------------------------


def _compute_overall(checks: list[ValidationCheck]) -> Literal["pass", "fail", "warn"]:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


# --- auxiliary (non-core) checks --------------------------------------------

# Path to the project-level kill file. Resolved relative to the validator
# module so it works from CLI, tests, and the API. If the file is missing
# the check is silently skipped -- it is auxiliary, not gating.
_KILL_FILE_PATH = Path(__file__).resolve().parent.parent / ".build" / "KILL_FILE.md"


def _parse_kill_file(path: Path) -> list[dict[str, str]]:
    """Parse KILL_FILE.md into a list of {id, title, symptom, fix} dicts.

    Best-effort regex parse -- if the file shape drifts, this returns
    [] and the caller emits no warnings. The kill file is markdown
    authored by humans, so we tolerate whitespace and missing fields.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError):
        return []
    entries: list[dict[str, str]] = []
    # Each entry starts with: ### KILL-NNNN: <title>
    # followed by labelled lines: - **Symptom:** ... / - **Fix:** ...
    pattern = re.compile(
        r"^### (KILL-\d{4}):\s*(.+?)$(.*?)(?=^### KILL-\d{4}:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    field_re = re.compile(
        r"^-\s*\*\*(Symptom|Fix|Context)\s*:\*\*\s*(.+?)$",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        kill_id, title, body = m.group(1), m.group(2).strip(), m.group(3)
        entry = {"id": kill_id, "title": title, "symptom": "", "fix": "", "context": ""}
        for fm in field_re.finditer(body):
            entry[fm.group(1).lower()] = fm.group(2).strip()
        entries.append(entry)
    return entries


def _check_kill_file_unaddressed(
    checks: list[ValidationCheck],
) -> list[str]:
    """Warn-only: cross-reference failing checks against KILL_FILE.md entries.

    Returns a list of human-readable warning strings (one per match).
    NOT a ``ValidationCheck`` -- this is reported via the report's
    ``warnings`` list, separate from the 12 core checks, and does NOT
    influence ``overall``.
    """
    failures = [c for c in checks if c.status == "fail"]
    if not failures:
        return []
    entries = _parse_kill_file(_KILL_FILE_PATH)
    if not entries:
        return []
    warnings: list[str] = []
    for failure in failures:
        haystack = " ".join(
            s for s in (failure.name, failure.message, failure.details) if s
        ).lower()
        if not haystack:
            continue
        for entry in entries:
            symptom = entry.get("symptom", "").lower()
            context = entry.get("context", "").lower()
            if not symptom and not context:
                continue
            # Token-overlap heuristic: any reasonably distinctive symptom
            # phrase substring in the failure haystack -> match.
            # Use the first 6 words of the symptom (or context fallback)
            # as the lookup key; tune later if false-positive rate hurts.
            needle_src = symptom or context
            needle_words = [w for w in re.split(r"\W+", needle_src) if len(w) > 4]
            if not needle_words:
                continue
            key_phrase = " ".join(needle_words[:3])
            if key_phrase and key_phrase in haystack:
                fix = entry.get("fix") or "(no fix recorded)"
                warnings.append(
                    f"failure '{failure.name}' matches {entry['id']} "
                    f"({entry['title']}); suggested fix: {fix}"
                )
                break  # one match per failure is enough
    return warnings


async def _finalise(
    tool_id: str,
    tool_path: Path,
    timestamp: datetime,
    checks: list[ValidationCheck],
    sample_inputs: dict[str, Any] | None,
    sample_output: dict[str, Any] | None,
    spawn_log: str | None,
    save_to_db: bool,
) -> ValidationReport:
    report = ValidationReport(
        tool_id=tool_id,
        tool_path=str(tool_path),
        timestamp=timestamp,
        overall=_compute_overall(checks),
        checks=checks,
        sample_inputs=sample_inputs,
        sample_output=sample_output,
        spawn_log=spawn_log,
        warnings=_check_kill_file_unaddressed(checks),
    )
    if save_to_db:
        try:
            settings = get_settings()
            payload = json.loads(report.model_dump_json())
            await db.save_validation_report(settings.db_path, payload)
            await db.prune_old_reports(settings.db_path, days=30)
        except Exception as exc:  # never let db trouble suppress the report
            logger.warning("could not persist validation report: %s", exc)
    return report


# --- orchestrator ------------------------------------------------------------


async def validate_tool(
    tool_path: Path, *, save_to_db: bool = True,
    reference_only: bool = False,
    fixture_filter: list[str] | None = None,
    tag_filter: list[str] | None = None,
) -> ValidationReport:
    """Run the twelve validator checks against ``tool_path``.

    Reads only — never modifies the tool. When ``save_to_db`` is true,
    writes the resulting report to ``validation_reports`` and prunes
    rows older than 30 days.

    ``reference_only`` skips the sample-run / output-conformance /
    streaming / clean-shutdown checks. The warm spawn still happens
    (check #6 needs the live process), but checks 8-10 are replaced by
    ``skip`` entries; check #12 then runs against the same warm process.

    ``fixture_filter`` and ``tag_filter`` narrow check #12 to a subset
    of fixtures (CLI: ``--fixture`` and ``--tag``).
    """

    timestamp = datetime.now(timezone.utc)
    tool_path = tool_path.resolve()
    checks: list[ValidationCheck] = []
    sample_inputs: dict[str, Any] | None = None
    sample_output: dict[str, Any] | None = None
    spawn_log: str | None = None
    fallback_id = tool_path.name

    # 1. folder structure
    folder_check = await _check_folder_structure(tool_path)
    checks.append(folder_check)
    if folder_check.status == "fail":
        return await _finalise(
            fallback_id, tool_path, timestamp, checks,
            sample_inputs, sample_output, spawn_log, save_to_db,
        )

    # 2. tool.json parses
    parse_check, schema = await _check_tool_json_parses(tool_path)
    checks.append(parse_check)
    if schema is None:
        return await _finalise(
            fallback_id, tool_path, timestamp, checks,
            sample_inputs, sample_output, spawn_log, save_to_db,
        )

    # 3. schema coherence
    coherence_check = await _check_schemas_coherent(schema)
    checks.append(coherence_check)
    if coherence_check.status == "fail":
        return await _finalise(
            schema.id, tool_path, timestamp, checks,
            sample_inputs, sample_output, spawn_log, save_to_db,
        )

    # 4. pyproject
    pyproject_check = await _check_pyproject(tool_path)
    checks.append(pyproject_check)
    if pyproject_check.status == "fail":
        return await _finalise(
            schema.id, tool_path, timestamp, checks,
            sample_inputs, sample_output, spawn_log, save_to_db,
        )

    # 5. venv
    venv_check = await _check_venv(tool_path)
    checks.append(venv_check)
    if venv_check.status == "fail":
        return await _finalise(
            schema.id, tool_path, timestamp, checks,
            sample_inputs, sample_output, spawn_log, save_to_db,
        )

    # 6-11: one subprocess covers spawn, schema fetch, sample run, streaming, shutdown.
    port = _free_port()
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0)) as client:
        try:
            process, ring, pump = await _spawn_for_validation(tool_path, schema, port)
        except FileNotFoundError as exc:
            checks.append(ValidationCheck(
                name="tool_spawns", status="fail",
                message=f"could not spawn subprocess: {exc}",
            ))
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )

        spawn_ok, spawn_error = await _poll_healthz(client, process, ring, port)
        if not spawn_ok:
            checks.append(ValidationCheck(
                name="tool_spawns", status="fail",
                message="tool failed to become healthy",
                details=spawn_error,
            ))
            spawn_log = ring.snapshot() or None
            await _terminate_for_validation(process, pump, grace=2.0)
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )
        checks.append(ValidationCheck(
            name="tool_spawns", status="pass",
            message=f"/healthz returned 200 on port {port}",
        ))

        # 7. schema matches disk
        try:
            disk = json.loads((tool_path / "tool.json").read_text(encoding="utf-8"))
            response = await client.get(f"http://127.0.0.1:{port}/schema", timeout=5.0)
            response.raise_for_status()
            live = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            checks.append(ValidationCheck(
                name="schema_matches_disk", status="fail",
                message=f"could not fetch /schema: {exc}",
            ))
            spawn_log = ring.snapshot() or None
            await _terminate_for_validation(process, pump)
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )

        diffs = _diff_schemas(disk, live)
        if diffs:
            detail_lines = [
                f"  {ptr}:\n    disk = {disk_v!r}\n    live = {live_v!r}"
                for ptr, disk_v, live_v in diffs[:20]
            ]
            extra = f"\n  ... and {len(diffs) - 20} more" if len(diffs) > 20 else ""
            checks.append(ValidationCheck(
                name="schema_matches_disk", status="fail",
                message=f"schema drift: {len(diffs)} field(s) differ",
                details="\n".join(detail_lines) + extra,
            ))
            spawn_log = ring.snapshot() or None
            await _terminate_for_validation(process, pump)
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )
        checks.append(ValidationCheck(
            name="schema_matches_disk", status="pass",
            message="tool.json matches /schema",
        ))

        # In --reference-only mode we skip checks 8/9/10 entirely and
        # jump straight to the reference-fixtures check, then shut down.
        if reference_only:
            for skipped_name in ("sample_run_succeeds", "output_conforms", "streaming_check"):
                checks.append(ValidationCheck(
                    name=skipped_name, status="skip",
                    message="skipped: --reference-only",
                ))
            ref_check, _results, ref_inputs, ref_outputs = await _check_reference_fixtures(
                tool_path, schema, client, port,
                fixture_filter=fixture_filter, tag_filter=tag_filter,
            )
            checks.append(ref_check)
            if ref_inputs is not None:
                sample_inputs = ref_inputs
            if ref_outputs is not None:
                sample_output = ref_outputs
            spawn_log = ring.snapshot() or None
            clean_exit, exit_code = await _terminate_for_validation(process, pump)
            checks.append(_clean_shutdown_check(clean_exit, exit_code))
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )

        # 8. sample run
        sample_inputs = generate_sample_inputs(schema)
        sample_payload = build_sample_run_payload(schema)
        # ``validator_timeout_override`` (per RESEARCH_tool_patterns) lets a
        # slow tool extend its sample-run budget without bumping the
        # production ``max_runtime_seconds``. Falls back to the declared
        # runtime cap + a small SAMPLE_RUN_PADDING margin.
        if schema.validator_timeout_override is not None:
            run_timeout = float(schema.validator_timeout_override)
        else:
            run_timeout = schema.max_runtime_seconds + SAMPLE_RUN_PADDING_S
        try:
            run_response = await client.post(
                f"http://127.0.0.1:{port}/run",
                json=sample_payload,
                timeout=run_timeout,
            )
        except httpx.HTTPError as exc:
            checks.append(ValidationCheck(
                name="sample_run_succeeds", status="fail",
                message=f"POST /run raised {type(exc).__name__}: {exc}",
                details=f"sample_inputs = {json.dumps(sample_inputs, default=str)[:1500]}",
            ))
            spawn_log = ring.snapshot() or None
            await _terminate_for_validation(process, pump)
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )
        if run_response.status_code != 200:
            checks.append(ValidationCheck(
                name="sample_run_succeeds", status="fail",
                message=f"POST /run returned HTTP {run_response.status_code}",
                details=run_response.text[:2_000],
            ))
            spawn_log = ring.snapshot() or None
            await _terminate_for_validation(process, pump)
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )
        try:
            sample_output = run_response.json()
        except json.JSONDecodeError as exc:
            checks.append(ValidationCheck(
                name="sample_run_succeeds", status="fail",
                message=f"/run response was not JSON: {exc}",
                details=run_response.text[:2_000],
            ))
            spawn_log = ring.snapshot() or None
            await _terminate_for_validation(process, pump)
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )
        checks.append(ValidationCheck(
            name="sample_run_succeeds", status="pass",
            message=f"POST /run returned 200 within {run_timeout:.0f}s",
        ))

        # 9. output conformance
        output_problems: list[str] = []
        declared_keys = [spec.key for spec in schema.outputs]
        warn_extras: list[str] = []
        if not isinstance(sample_output, dict):
            output_problems.append(
                f"response body was not a JSON object (got {type(sample_output).__name__})"
            )
        else:
            for spec in schema.outputs:
                if spec.key not in sample_output:
                    output_problems.append(f"missing output key: {spec.key!r}")
                    continue
                status, message = _check_output_value(spec, sample_output[spec.key])
                if status == "fail" and message:
                    output_problems.append(message)
            warn_extras = [
                key for key in sample_output.keys() if key not in declared_keys
            ]

        if output_problems:
            checks.append(ValidationCheck(
                name="output_conforms", status="fail",
                message=f"{len(output_problems)} output conformance issue(s)",
                details="\n".join(output_problems),
            ))
            spawn_log = ring.snapshot() or None
            await _terminate_for_validation(process, pump)
            return await _finalise(
                schema.id, tool_path, timestamp, checks,
                sample_inputs, sample_output, spawn_log, save_to_db,
            )
        if warn_extras:
            checks.append(ValidationCheck(
                name="output_conforms", status="warn",
                message=f"response contained {len(warn_extras)} undeclared key(s)",
                details=f"extra keys: {warn_extras}",
            ))
        else:
            checks.append(ValidationCheck(
                name="output_conforms", status="pass",
                message=f"all {len(declared_keys)} declared output(s) present and conformant",
            ))

        # 10. streaming check
        streaming_outputs = [spec for spec in schema.outputs if spec.streaming]
        if not streaming_outputs:
            checks.append(ValidationCheck(
                name="streaming_check", status="skip",
                message="no outputs declared streaming",
            ))
        else:
            checks.append(await _check_streaming(client, sample_output, port))

        # 11. reference fixtures (check #12 in docs / sample id 11).
        # Runs against the same warm process used by checks 6-10.
        ref_check, _results, ref_inputs, ref_outputs = await _check_reference_fixtures(
            tool_path, schema, client, port,
            fixture_filter=fixture_filter, tag_filter=tag_filter,
        )
        checks.append(ref_check)
        # Surface the first failing fixture's inputs/outputs on the
        # report so the renderer can show what diverged.
        if ref_inputs is not None:
            sample_inputs = ref_inputs
        if ref_outputs is not None:
            sample_output = ref_outputs

        # 12. clean shutdown (executes last regardless of #12 outcome).
        spawn_log = ring.snapshot() or None
        clean_exit, exit_code = await _terminate_for_validation(process, pump)
        checks.append(_clean_shutdown_check(clean_exit, exit_code))

    return await _finalise(
        schema.id, tool_path, timestamp, checks,
        sample_inputs, sample_output, spawn_log, save_to_db,
    )


def _clean_shutdown_check(clean_exit: bool, exit_code: int | None) -> ValidationCheck:
    """Helper so check #11 (clean_shutdown) can be appended from two paths."""

    if clean_exit:
        return ValidationCheck(
            name="clean_shutdown", status="pass",
            message=(
                f"process exited within {SHUTDOWN_GRACE_S:.0f}s of "
                f"SIGTERM (exit={exit_code})"
            ),
        )
    return ValidationCheck(
        name="clean_shutdown", status="warn",
        message=(
            f"process did not exit within {SHUTDOWN_GRACE_S:.0f}s; "
            f"killed (exit={exit_code})"
        ),
    )


def validate_tool_sync(
    tool_path: Path, *, save_to_db: bool = True,
    reference_only: bool = False,
    fixture_filter: list[str] | None = None,
    tag_filter: list[str] | None = None,
) -> ValidationReport:
    """Synchronous wrapper around :func:`validate_tool` for CLI use."""

    return asyncio.run(validate_tool(
        tool_path,
        save_to_db=save_to_db,
        reference_only=reference_only,
        fixture_filter=fixture_filter,
        tag_filter=tag_filter,
    ))


def update_reference_fixtures_sync(
    tool_path: Path,
    *,
    fixture_filter: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Sync wrapper for :func:`update_reference_fixtures` (CLI use)."""

    return asyncio.run(update_reference_fixtures(
        tool_path,
        fixture_filter=fixture_filter,
        dry_run=dry_run,
    ))
