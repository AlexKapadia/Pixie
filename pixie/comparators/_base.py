"""Base models and helpers for the comparator package.

The check #12 ("reference_fixtures_match") infrastructure boils down to
three building blocks:

* a structured ``Diff`` that every comparator returns (or ``None`` to
  signal "match");
* a Pydantic-validated tolerance configuration loaded from disk; and
* a 4-level tolerance lookup so a fixture, project, type-default and
  built-in default can layer on top of each other.

This module is dependency-free; the per-type comparator modules import
from here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


__all__ = [
    "Diff",
    "FixtureResult",
    "ReferenceFixture",
    "ToleranceConfig",
    "TruncationLimit",
    "BUILTIN_DEFAULTS",
    "merged_tolerance",
    "load_tolerance_yaml",
    "load_fixtures",
    "truncate_for_display",
]


TruncationLimit = 400


# ----------------------------- Diff & result ----------------------------------


class Diff(BaseModel):
    """A single mismatch produced by a comparator.

    ``None`` from :func:`pixie.comparators.compare` means "match".
    A populated ``Diff`` means "no match"; ``metric`` carries the
    human-readable summary used by the report renderer.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    output_key: str
    output_type: str
    comparator: str
    expected: Any = None
    actual: Any = None
    metric: str | None = None
    path: str | None = None


class FixtureResult(BaseModel):
    """One fixture's pass/fail/skip outcome from check #12."""

    name: str
    status: Literal["pass", "fail", "skip"]
    message: str
    diffs: list[Diff] = Field(default_factory=list)
    source: str | None = None


# ----------------------------- Reference fixture ------------------------------


class ReferenceFixture(BaseModel):
    """Schema for an individual ``fixture_*.json`` file."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source: str | None = None
    inputs: dict[str, Any]
    expected_outputs: dict[str, Any]
    tolerance: dict[str, dict[str, Any]] = Field(default_factory=dict)
    skip_reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    # Per-fixture timeout in seconds (overrides tool-level + 30s default).
    validator_timeout_override: float | None = None
    # Filled in by the loader; never declared in JSON.
    file_path: str | None = None


# ----------------------------- Tolerance schema -------------------------------


class _NumericTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rtol: float = 1.0e-6
    atol: float = 1.0e-9


class _TextTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["exact", "exact_after_normalize_whitespace", "json_normalized"] = "exact"


class _BoolTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["exact"] = "exact"


class _KvTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["dict_per_value"] = "dict_per_value"
    allow_extra: bool = False
    float_rtol: float = 1.0e-6
    float_atol: float = 1.0e-9


class _TableTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["rows_unordered", "rows_ordered"] = "rows_unordered"
    float_rtol: float = 1.0e-6
    float_atol: float = 1.0e-9


class _ChartDataTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal[
        "data_only", "slices_unordered", "values_unordered",
        "series_summary", "matrix_elementwise", "rows_ordered",
        "graph_set", "tree_set", "skip",
    ] = "data_only"
    series_match: Literal["by_name", "by_index"] = "by_name"
    float_rtol: float = 1.0e-6
    float_atol: float = 1.0e-9


class _MapTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal[
        "set_equal_after_round_coords_4dp",
        "ordered_after_round_coords_4dp",
        "keyed_values",
        "skip",
    ] = "set_equal_after_round_coords_4dp"
    round_digits: int = Field(default=4, ge=0, le=10)
    float_rtol: float = 1.0e-6
    float_atol: float = 1.0e-9


class _ImageTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["ssim", "ssim_per_image", "ssim_pair", "size_sha256", "skip"] = "ssim"
    min_ssim: float = Field(default=0.95, ge=0.0, le=1.0)


class _AudioTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["spectrogram_l2", "size_sha256", "skip"] = "spectrogram_l2"
    max_l2: float = Field(default=0.05, ge=0.0)
    sample_rate: int = 22050
    n_mels: int = 128


class _VideoTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["skip", "per_frame_ssim_mean"] = "skip"
    min_ssim: float = Field(default=0.90, ge=0.0, le=1.0)


class _TreeTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["structural"] = "structural"
    children_order: Literal["unordered", "ordered"] = "unordered"


class _TimelineTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["rows_ordered"] = "rows_ordered"
    allow_regex: bool = False


class _ProgressTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["skip"] = "skip"


class _FileTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["sha256", "mime_dispatch", "skip"] = "mime_dispatch"
    float_rtol: float = 1.0e-6


class _DiffTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["exact"] = "exact"


class _LatexTol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    compare: Literal["exact", "exact_after_normalize_whitespace"] = "exact_after_normalize_whitespace"


class _ToleranceDefaults(BaseModel):
    """Per-type defaults overlay applied below per-key overrides."""

    model_config = ConfigDict(extra="forbid")

    # scalars and text
    number: _NumericTol = _NumericTol()
    boolean: _BoolTol = _BoolTol()
    text: _TextTol = _TextTol()
    markdown: _TextTol = _TextTol(compare="exact_after_normalize_whitespace")
    code: _TextTol = _TextTol()
    latex: _LatexTol = _LatexTol()
    stream_text: _TextTol = _TextTol()
    diff: _DiffTol = _DiffTol()
    kv: _KvTol = _KvTol()
    table: _TableTol = _TableTol()
    tree: _TreeTol = _TreeTol()
    # charts
    chart_line: _ChartDataTol = _ChartDataTol(compare="data_only")
    chart_bar: _ChartDataTol = _ChartDataTol(compare="data_only")
    chart_area: _ChartDataTol = _ChartDataTol(compare="data_only")
    chart_scatter: _ChartDataTol = _ChartDataTol(compare="data_only")
    chart_pie: _ChartDataTol = _ChartDataTol(compare="slices_unordered")
    chart_histogram: _ChartDataTol = _ChartDataTol(compare="values_unordered")
    chart_boxplot: _ChartDataTol = _ChartDataTol(compare="series_summary")
    chart_heatmap: _ChartDataTol = _ChartDataTol(compare="matrix_elementwise")
    chart_candlestick: _ChartDataTol = _ChartDataTol(compare="rows_ordered")
    chart_radar: _ChartDataTol = _ChartDataTol(compare="data_only")
    chart_sankey: _ChartDataTol = _ChartDataTol(compare="graph_set")
    chart_treemap: _ChartDataTol = _ChartDataTol(compare="tree_set")
    chart_network: _ChartDataTol = _ChartDataTol(compare="graph_set")
    # maps
    map_points: _MapTol = _MapTol(compare="set_equal_after_round_coords_4dp")
    map_heatmap: _MapTol = _MapTol(compare="set_equal_after_round_coords_4dp")
    map_choropleth: _MapTol = _MapTol(compare="keyed_values")
    map_polygons: _MapTol = _MapTol(compare="set_equal_after_round_coords_4dp")
    map_route: _MapTol = _MapTol(compare="ordered_after_round_coords_4dp")
    # media
    image: _ImageTol = _ImageTol(compare="ssim")
    image_grid: _ImageTol = _ImageTol(compare="ssim_per_image")
    image_compare: _ImageTol = _ImageTol(compare="ssim_pair")
    audio: _AudioTol = _AudioTol()
    video: _VideoTol = _VideoTol()
    # timeline family
    timeline: _TimelineTol = _TimelineTol()
    gantt: _TimelineTol = _TimelineTol()
    log: _TimelineTol = _TimelineTol(allow_regex=False)
    progress: _ProgressTol = _ProgressTol()
    # file
    file: _FileTol = _FileTol()


class _ToleranceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_extra_output_key: Literal["warn", "fail", "ignore"] = "warn"
    on_missing_expected_key: Literal["warn", "fail", "ignore"] = "fail"
    truncate_diff_chars: int = TruncationLimit


class ToleranceConfig(BaseModel):
    """Parsed ``reference/tolerance.yaml`` (or built-in defaults)."""

    model_config = ConfigDict(extra="forbid")

    defaults: _ToleranceDefaults = _ToleranceDefaults()
    overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    options: _ToleranceOptions = _ToleranceOptions()
    # Populated by the loader; not part of the on-disk schema.
    errors: list[str] = Field(default_factory=list, exclude=True)

    def defaults_for(self, output_type: str) -> dict[str, Any]:
        """Return the per-type defaults dict for ``output_type``.

        Returns an empty dict when the type has no entry — the comparator
        will fall back to :data:`BUILTIN_DEFAULTS`.
        """

        block = getattr(self.defaults, output_type, None)
        if block is None:
            return {}
        return block.model_dump()


# ----------------------------- Built-in defaults ------------------------------

# Last-resort tolerance dict used when neither the fixture, the
# project-level tolerance.yaml, nor the Pydantic default supplies a
# concrete value. The comparator implementations rely on these keys
# being present; never let a comparator hit a missing key.

BUILTIN_DEFAULTS: dict[str, dict[str, Any]] = {
    "number": {"compare": "numeric_isclose", "rtol": 1.0e-6, "atol": 1.0e-9},
    "boolean": {"compare": "exact"},
    "text": {"compare": "exact"},
    "markdown": {"compare": "exact_after_normalize_whitespace"},
    "code": {"compare": "exact"},
    "latex": {"compare": "exact_after_normalize_whitespace"},
    "stream_text": {"compare": "exact"},
    "diff": {"compare": "exact"},
    "kv": {"compare": "dict_per_value", "allow_extra": False,
           "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "table": {"compare": "rows_unordered", "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "tree": {"compare": "structural", "children_order": "unordered"},
    "chart_line": {"compare": "data_only", "series_match": "by_name",
                   "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_bar": {"compare": "data_only", "series_match": "by_name",
                  "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_area": {"compare": "data_only", "series_match": "by_name",
                   "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_scatter": {"compare": "data_only", "series_match": "by_name",
                      "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_pie": {"compare": "slices_unordered",
                  "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_histogram": {"compare": "values_unordered",
                        "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_boxplot": {"compare": "series_summary",
                      "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_heatmap": {"compare": "matrix_elementwise",
                      "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_candlestick": {"compare": "rows_ordered",
                          "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_radar": {"compare": "data_only",
                    "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_sankey": {"compare": "graph_set",
                     "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_treemap": {"compare": "tree_set",
                      "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "chart_network": {"compare": "graph_set",
                      "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "map_points": {"compare": "set_equal_after_round_coords_4dp", "round_digits": 4,
                   "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "map_heatmap": {"compare": "set_equal_after_round_coords_4dp", "round_digits": 4,
                    "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "map_choropleth": {"compare": "keyed_values",
                       "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "map_polygons": {"compare": "set_equal_after_round_coords_4dp", "round_digits": 4,
                     "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "map_route": {"compare": "ordered_after_round_coords_4dp", "round_digits": 4,
                  "float_rtol": 1.0e-6, "float_atol": 1.0e-9},
    "image": {"compare": "ssim", "min_ssim": 0.95},
    "image_grid": {"compare": "ssim_per_image", "min_ssim": 0.95},
    "image_compare": {"compare": "ssim_pair", "min_ssim": 0.95},
    "audio": {"compare": "spectrogram_l2", "max_l2": 0.05,
              "sample_rate": 22050, "n_mels": 128},
    "video": {"compare": "skip", "min_ssim": 0.90},
    "timeline": {"compare": "rows_ordered"},
    "gantt": {"compare": "rows_ordered"},
    "log": {"compare": "rows_ordered", "allow_regex": False},
    "progress": {"compare": "skip"},
    "file": {"compare": "mime_dispatch", "float_rtol": 1.0e-6},
}


# ----------------------------- Tolerance lookup -------------------------------


def merged_tolerance(
    output_key: str,
    output_type: str,
    tolerance_config: ToleranceConfig,
    fixture_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve the effective tolerance dict for ``(output_key, output_type)``.

    Hierarchy, highest priority first (later sources never overwrite
    earlier ones — RESEARCH §3):

    1. Fixture override -- ``fixture.tolerance[output_key]``
    2. Project override -- ``tolerance.yaml::overrides[output_key]``
    3. Project default by type -- ``tolerance.yaml::defaults[output_type]``
    4. Built-in default by type -- :data:`BUILTIN_DEFAULTS[output_type]`

    Merge is shallow on the inner tolerance dict so an override of
    ``{rtol: 1e-4}`` for a table replaces only ``rtol`` and inherits
    the rest from the next layer.
    """

    builtin = dict(BUILTIN_DEFAULTS.get(output_type, {}))
    project_default = tolerance_config.defaults_for(output_type)
    project_override = dict(tolerance_config.overrides.get(output_key, {}))
    fixture_override = dict((fixture_overrides or {}).get(output_key, {}))

    # Python 3.12 dict-union; right wins, so layer cheapest -> richest.
    merged = builtin | project_default | project_override | fixture_override
    return merged


# ----------------------------- Loaders ---------------------------------------


def load_tolerance_yaml(path: Path) -> ToleranceConfig:
    """Parse and validate ``tolerance.yaml``. Always returns a config.

    Missing file -> empty defaults. Parse / validation failures populate
    :attr:`ToleranceConfig.errors`; the validator surfaces them as a fail.
    """

    if not path.is_file():
        return ToleranceConfig()

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        config = ToleranceConfig()
        config.errors.append(f"could not read tolerance.yaml: {exc}")
        return config

    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        config = ToleranceConfig()
        # Surface line number + the parser's own diagnostic. PyYAML's
        # str(exc) is multi-line and noisy; problem_mark.line is 0-based.
        mark = getattr(exc, "problem_mark", None)
        problem = getattr(exc, "problem", None)
        if mark is not None and problem:
            line_no = mark.line + 1  # convert to 1-based for humans
            config.errors.append(
                f"could not parse YAML at line {line_no}: {problem}"
            )
        else:
            config.errors.append(f"could not parse YAML: {exc}")
        return config

    if not isinstance(data, dict):
        config = ToleranceConfig()
        config.errors.append(
            f"tolerance.yaml top-level must be a mapping, got {type(data).__name__}"
        )
        return config

    try:
        return ToleranceConfig.model_validate(data)
    except ValidationError as exc:
        config = ToleranceConfig()
        scalar_where_dict_seen = False
        for error in exc.errors():
            loc = ".".join(str(part) for part in error.get("loc", ()))
            config.errors.append(f"{loc or '<root>'}: {error.get('msg')}")
            # Detect the classic 'key:{...}' (missing space) footgun:
            # pydantic sees a string where it expected a dict.
            err_type = error.get("type", "")
            input_value = error.get("input")
            if (
                err_type in {"model_type", "dict_type"}
                and isinstance(input_value, str)
            ):
                scalar_where_dict_seen = True
        if scalar_where_dict_seen:
            config.errors.append(
                "YAML hint: 'key:{...}' without a space after the colon is a "
                "scalar, not a dict. Either write 'key: {...}' or use block style."
            )
        return config


def load_fixtures(
    fixture_paths: list[Path],
    declared_input_keys: set[str] | None = None,
    declared_output_keys: set[str] | None = None,
) -> tuple[list[ReferenceFixture], list[str]]:
    """Load and validate fixture files. Returns ``(loaded, errors)``.

    ``declared_input_keys`` / ``declared_output_keys`` are used for soft
    sanity checks: extra unknown output keys in ``expected_outputs`` are
    reported as load errors (the validator treats them as fatal so that
    a typo doesn't silently pass).
    """

    loaded: list[ReferenceFixture] = []
    errors: list[str] = []

    for path in fixture_paths:
        rel = path.name
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{rel}: could not read file: {exc}")
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: not valid JSON: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(
                f"{rel}: top-level must be a JSON object, got {type(data).__name__}"
            )
            continue
        try:
            fixture = ReferenceFixture.model_validate(data)
        except ValidationError as exc:
            problems = []
            for error in exc.errors():
                loc = ".".join(str(part) for part in error.get("loc", ()))
                problems.append(f"  {loc or '<root>'}: {error.get('msg')}")
            errors.append(f"{rel}: invalid fixture\n" + "\n".join(problems))
            continue
        fixture.file_path = str(path)

        if declared_output_keys is not None:
            unknown = sorted(
                set(fixture.expected_outputs.keys()) - declared_output_keys
            )
            if unknown:
                errors.append(
                    f"{rel}: expected_outputs references undeclared output key(s): "
                    f"{unknown}"
                )
                continue

        loaded.append(fixture)

    return loaded, errors


# ----------------------------- Display helpers --------------------------------


def truncate_for_display(value: Any, limit: int = TruncationLimit) -> str:
    """Return a JSON-ish stringification of ``value`` truncated to ``limit``."""

    try:
        text = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 4)] + " ..."
