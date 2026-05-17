"""Tool discovery and Pydantic schema models.

Walks ``tools/`` and parses every ``tool.json`` against the
``ToolSchema`` Pydantic v2 model. Returns ``DiscoveredTool`` entries
that include parse errors so the sidebar can surface broken tools
instead of silently hiding them. Pixie never imports tool code;
discovery is a read-only filesystem scan.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("pixie.discovery")


# --- common option types -----------------------------------------------------


class SelectOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | int | float | bool
    label: str


class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    type: str


class ShowIf(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    equals: Any


# --- input common base -------------------------------------------------------


class _InputBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    description: str | None = None
    default: Any | None = None
    required: bool = True
    group: str | None = None
    show_if: ShowIf | None = None


# --- input variants ----------------------------------------------------------


class TextInput(_InputBase):
    type: Literal["text"]
    placeholder: str | None = None
    max_length: int | None = None


class TextareaInput(_InputBase):
    type: Literal["textarea"]
    placeholder: str | None = None
    max_length: int | None = None
    monospace: bool = False


class NumberInput(_InputBase):
    type: Literal["number"]
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None


class SliderInput(_InputBase):
    type: Literal["slider"]
    min: float
    max: float
    step: float | None = None
    range: bool = False


class SelectInput(_InputBase):
    type: Literal["select"]
    options: list[SelectOption]
    searchable: bool = False


class MultiselectInput(_InputBase):
    type: Literal["multiselect"]
    options: list[SelectOption]


class CheckboxInput(_InputBase):
    type: Literal["checkbox"]


class ToggleInput(_InputBase):
    type: Literal["toggle"]


class RadioInput(_InputBase):
    type: Literal["radio"]
    options: list[SelectOption]


class DateInput(_InputBase):
    type: Literal["date"]
    min: str | None = None
    max: str | None = None


class TimeInput(_InputBase):
    type: Literal["time"]


class DatetimeInput(_InputBase):
    type: Literal["datetime"]


class DateRangeInput(_InputBase):
    type: Literal["date_range"]


class FileInput(_InputBase):
    type: Literal["file"]
    accept: str | list[str] | None = None
    max_size_mb: int | None = None
    multiple: bool = False


class ImageInput(_InputBase):
    type: Literal["image"]
    max_size_mb: int | None = None
    multiple: bool = False


class AudioInput(_InputBase):
    type: Literal["audio"]
    max_size_mb: int | None = None


class ColourInput(_InputBase):
    type: Literal["colour"]


class JsonInput(_InputBase):
    type: Literal["json"]
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


class CodeInput(_InputBase):
    type: Literal["code"]
    language: str | None = None


class MarkdownInput(_InputBase):
    type: Literal["markdown"]


class TagsInput(_InputBase):
    type: Literal["tags"]
    suggestions: list[str] = Field(default_factory=list)


class AutocompleteInput(_InputBase):
    type: Literal["autocomplete"]
    endpoint: str


class TableInput(_InputBase):
    type: Literal["table"]
    columns: list[ColumnSpec]
    min_rows: int | None = None
    max_rows: int | None = None


class MapPointInput(_InputBase):
    type: Literal["map_point"]
    default_center: list[float] | None = None
    default_zoom: int | None = None


class MapBboxInput(_InputBase):
    type: Literal["map_bbox"]
    default_center: list[float] | None = None
    default_zoom: int | None = None


class MapPolygonInput(_InputBase):
    type: Literal["map_polygon"]
    default_center: list[float] | None = None
    default_zoom: int | None = None


class MapMultipointInput(_InputBase):
    type: Literal["map_multipoint"]
    default_center: list[float] | None = None
    default_zoom: int | None = None


class HiddenInput(_InputBase):
    type: Literal["hidden"]


InputSpec = Annotated[
    Union[
        TextInput, TextareaInput, NumberInput, SliderInput, SelectInput,
        MultiselectInput, CheckboxInput, ToggleInput, RadioInput, DateInput,
        TimeInput, DatetimeInput, DateRangeInput, FileInput, ImageInput,
        AudioInput, ColourInput, JsonInput, CodeInput, MarkdownInput,
        TagsInput, AutocompleteInput, TableInput, MapPointInput, MapBboxInput,
        MapPolygonInput, MapMultipointInput, HiddenInput,
    ],
    Field(discriminator="type"),
]


# --- output common base ------------------------------------------------------


class _OutputBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    description: str | None = None
    caption: str | None = None
    unit: str | None = None
    streaming: bool = False
    layout: Literal["panel", "tab", "inline"] = "panel"
    # Export matrix (DECISIONS s38 / RESEARCH_export_formats). ``None``
    # tells the exporter dispatcher to pick its built-in default for the
    # output type; an explicit value lets a tool author override either
    # the default extension or restrict which formats appear in the UI.
    default_export_format: str | None = None
    supported_export_formats: list[str] | None = None
    # Note: cursor-paginated table outputs use response-side fields
    # ``next_cursor`` and ``total_rows`` on the OUTPUT VALUE (the JSON the
    # tool returns), not on this spec. They require no schema change here.


# --- output variants ---------------------------------------------------------


class TextOutput(_OutputBase):
    type: Literal["text"]


class MarkdownOutput(_OutputBase):
    type: Literal["markdown"]


class NumberOutput(_OutputBase):
    type: Literal["number"]
    format: Literal["currency", "percent", "scientific", "decimal"] = "decimal"
    precision: int | None = None


class BooleanOutput(_OutputBase):
    type: Literal["boolean"]
    true_label: str | None = None
    false_label: str | None = None


class TableOutput(_OutputBase):
    type: Literal["table"]
    columns: list[ColumnSpec] | None = None
    downloadable: bool = False


class KvOutput(_OutputBase):
    type: Literal["kv"]


class ChartLineOutput(_OutputBase):
    type: Literal["chart_line"]
    x_label: str | None = None
    y_label: str | None = None
    log_x: bool = False
    log_y: bool = False


class ChartBarOutput(_OutputBase):
    type: Literal["chart_bar"]


class ChartScatterOutput(_OutputBase):
    type: Literal["chart_scatter"]


class ChartAreaOutput(_OutputBase):
    type: Literal["chart_area"]
    x_label: str | None = None
    y_label: str | None = None
    log_x: bool = False
    log_y: bool = False


class ChartPieOutput(_OutputBase):
    type: Literal["chart_pie"]


class ChartHistogramOutput(_OutputBase):
    type: Literal["chart_histogram"]


class ChartBoxplotOutput(_OutputBase):
    type: Literal["chart_boxplot"]


class ChartHeatmapOutput(_OutputBase):
    type: Literal["chart_heatmap"]


class ChartCandlestickOutput(_OutputBase):
    type: Literal["chart_candlestick"]


class ChartRadarOutput(_OutputBase):
    type: Literal["chart_radar"]


class ChartSankeyOutput(_OutputBase):
    type: Literal["chart_sankey"]


class ChartTreemapOutput(_OutputBase):
    type: Literal["chart_treemap"]


class ChartNetworkOutput(_OutputBase):
    type: Literal["chart_network"]


class MapPointsOutput(_OutputBase):
    type: Literal["map_points"]
    default_center: list[float] | None = None
    default_zoom: int | None = None


class MapHeatmapOutput(_OutputBase):
    type: Literal["map_heatmap"]


class MapChoroplethOutput(_OutputBase):
    type: Literal["map_choropleth"]


class MapPolygonsOutput(_OutputBase):
    type: Literal["map_polygons"]


class MapRouteOutput(_OutputBase):
    type: Literal["map_route"]


class ImageOutput(_OutputBase):
    type: Literal["image"]


class ImageGridOutput(_OutputBase):
    type: Literal["image_grid"]


class ImageCompareOutput(_OutputBase):
    type: Literal["image_compare"]


class AudioOutput(_OutputBase):
    type: Literal["audio"]


class VideoOutput(_OutputBase):
    type: Literal["video"]


class LatexOutput(_OutputBase):
    type: Literal["latex"]


class CodeOutput(_OutputBase):
    type: Literal["code"]
    language: str | None = None


class DiffOutput(_OutputBase):
    type: Literal["diff"]


class TreeOutput(_OutputBase):
    type: Literal["tree"]


class TimelineOutput(_OutputBase):
    type: Literal["timeline"]


class GanttOutput(_OutputBase):
    type: Literal["gantt"]


class ProgressOutput(_OutputBase):
    type: Literal["progress"]


class LogOutput(_OutputBase):
    type: Literal["log"]


class StreamTextOutput(_OutputBase):
    type: Literal["stream_text"]


class FileOutput(_OutputBase):
    type: Literal["file"]


OutputSpec = Annotated[
    Union[
        TextOutput, MarkdownOutput, NumberOutput, BooleanOutput, TableOutput,
        KvOutput, ChartLineOutput, ChartBarOutput, ChartScatterOutput,
        ChartAreaOutput, ChartPieOutput, ChartHistogramOutput, ChartBoxplotOutput,
        ChartHeatmapOutput, ChartCandlestickOutput, ChartRadarOutput,
        ChartSankeyOutput, ChartTreemapOutput, ChartNetworkOutput,
        MapPointsOutput, MapHeatmapOutput, MapChoroplethOutput,
        MapPolygonsOutput, MapRouteOutput, ImageOutput, ImageGridOutput,
        ImageCompareOutput, AudioOutput, VideoOutput, LatexOutput, CodeOutput,
        DiffOutput, TreeOutput, TimelineOutput, GanttOutput, ProgressOutput,
        LogOutput, StreamTextOutput, FileOutput,
    ],
    Field(discriminator="type"),
]


# --- top-level tool schema ---------------------------------------------------


class SecretSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    description: str | None = None
    required: bool = False


class ToolSchema(BaseModel):
    """Parsed tool.json. Top-level fields per Master Prompt s tool.json."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None = None
    version: str | None = None
    category: str | None = None
    icon: str | None = None
    layout: Literal["form", "chat", "split"] = "form"
    warm_keep_seconds: int = 300
    max_memory_mb: int = 512
    max_runtime_seconds: int = 60
    secrets: list[SecretSpec] = Field(default_factory=list)
    inputs: list[InputSpec]
    outputs: list[OutputSpec]
    # Polish-pass additions (DECISIONS s16, s21-30, s tool patterns).
    # Categories accept ``/``-delimited hierarchies (e.g. ``finance/quant``);
    # rendering treats segments as breadcrumbs in the sidebar. No schema
    # change needed for that — the convention is enforced by the renderer.
    schema_version: str = "1.0"
    concurrent: bool = True
    validator_timeout_override: int | None = None
    requires_data_persistence: bool = False
    input_transport: Literal["json", "multipart"] = "json"
    provides_file_endpoint: bool = False
    provides_autocomplete: bool = False
    retain_runs: int = 100
    tags: list[str] = Field(default_factory=list)
    archived: bool = False
    pinned_warm: bool = False
    entrypoint: str = "main.py"
    package: str | None = None
    workspace_default: str | None = None


# --- discovery ---------------------------------------------------------------


def _venv_python(tool_path: Path) -> Path:
    if sys.platform == "win32":
        return tool_path / ".venv" / "Scripts" / "python.exe"
    return tool_path / ".venv" / "bin" / "python"


@dataclass
class DiscoveredTool:
    """A single entry under ``tools/``. Either schema is set, or parse_error is."""

    tool_id: str
    path: Path
    schema: ToolSchema | None
    parse_error: str | None
    has_venv: bool

    @property
    def has_reference_fixtures(self) -> bool:
        """True when ``reference/fixture_*.json`` files exist on disk.

        Used by the validator (check #12) and the reference routes layer
        to know whether to invite the accuracy check without parsing the
        fixture files. Cheap: one ``glob`` call.
        """

        reference_dir = self.path / "reference"
        if not reference_dir.is_dir():
            return False
        return any(reference_dir.glob("fixture_*.json"))


def load_tool_schema(tool_path: Path) -> ToolSchema:
    """Parse and validate a single ``tool.json`` file. Raises on error."""

    raw = (tool_path / "tool.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    return ToolSchema.model_validate(data)


def _load_one_tool(entry: Path) -> DiscoveredTool:
    """Parse one tool folder. Returns a ``DiscoveredTool`` with either a
    valid schema or a populated ``parse_error``. Never raises.
    """

    tool_json = entry / "tool.json"
    has_venv = _venv_python(entry).exists()
    if not tool_json.exists():
        return DiscoveredTool(
            tool_id=entry.name, path=entry, schema=None,
            parse_error="tool.json missing", has_venv=has_venv,
        )
    try:
        schema = load_tool_schema(entry)
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        return DiscoveredTool(
            tool_id=entry.name, path=entry, schema=None,
            parse_error=str(exc), has_venv=has_venv,
        )
    return DiscoveredTool(
        tool_id=schema.id, path=entry, schema=schema,
        parse_error=None, has_venv=has_venv,
    )


def discover_tools(tools_dir: Path) -> list[DiscoveredTool]:
    """Scan direct subfolders of ``tools_dir`` and parse each ``tool.json``.

    Parse failures are returned as ``DiscoveredTool`` entries with
    ``schema=None`` and ``parse_error`` set so the sidebar can still
    surface broken tools.
    """

    if not tools_dir.exists():
        logger.warning("tools dir %s does not exist", tools_dir)
        return []

    discovered: list[DiscoveredTool] = []
    for entry in sorted(tools_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        discovered.append(_load_one_tool(entry))
    return discovered


# --- parallel + hash-cached discovery ---------------------------------------

# Files whose mtime + size feed the discovery hash. If any of these change,
# the cached ``DiscoveredTool`` must be reparsed.
_HASH_INPUT_FILES: tuple[str, ...] = ("tool.json", "pyproject.toml", "main.py")


def _discovery_hash(tool_path: Path) -> str:
    """SHA1 of (mtime, size) for the three discovery-relevant tool files.

    Cheap to compute (three stats), stable across process restarts, and
    invalidates whenever any of ``tool.json``, ``pyproject.toml`` or
    ``main.py`` changes.
    """

    digest = hashlib.sha1()
    for name in _HASH_INPUT_FILES:
        path = tool_path / name
        try:
            stat = path.stat()
            digest.update(name.encode("utf-8"))
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
            digest.update(b":")
            digest.update(str(stat.st_size).encode("ascii"))
            digest.update(b"|")
        except OSError:
            digest.update(name.encode("utf-8"))
            digest.update(b":missing|")
    return digest.hexdigest()


def needs_revalidation(tool_path: Path, current_hash: str | None) -> bool:
    """Return True when the on-disk hash differs from ``current_hash``.

    Pass ``None`` to indicate the database has no prior fingerprint for
    this tool — that always counts as needing revalidation.
    """

    if not current_hash:
        return True
    return _discovery_hash(tool_path) != current_hash


async def discover_tools_parallel(
    tools_dir: Path, concurrency: int = 8
) -> list[DiscoveredTool]:
    """Asynchronous, fan-out version of :func:`discover_tools`.

    Bound by ``asyncio.Semaphore(concurrency)`` (default 8) so the
    filesystem stat + Pydantic parse can overlap on the threadpool
    without thrashing the syscall layer. At N=200 this drops discovery
    from ~8 s serial to ~1 s (see ``RESEARCH_scale.md`` §4.1).

    Identical return shape to :func:`discover_tools` — order is preserved
    via ``sorted(folders)`` so callers can rely on alphabetical ordering.
    """

    if not tools_dir.exists():
        logger.warning("tools dir %s does not exist", tools_dir)
        return []

    folders = [
        entry for entry in sorted(tools_dir.iterdir())
        if entry.is_dir() and not entry.name.startswith(".")
    ]
    if not folders:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _load_with_limit(entry: Path) -> DiscoveredTool:
        async with semaphore:
            return await asyncio.to_thread(_load_one_tool, entry)

    return list(await asyncio.gather(*(_load_with_limit(f) for f in folders)))
