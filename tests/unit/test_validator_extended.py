"""Extended unit tests for ``pixie.validator``.

Focuses on the pure helpers + the static check builders. Live-spawn
checks (#5 venv, #6 spawn, #7 schema_endpoint, #8 sample_run, #10 streaming,
#11 graceful_shutdown) are covered by the integration suite where a real
venv is available.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from pixie.discovery import ToolSchema
from pixie.validator import (
    ValidationCheck,
    ValidationReport,
    _check_folder_structure,
    _check_output_value,
    _check_pyproject,
    _check_schemas_coherent,
    _check_tool_json_parses,
    _check_venv,
    _clean_shutdown_check,
    _compute_overall,
    _diff_schemas,
    _extract_dep_names,
    _looks_like_non_pypi,
    build_sample_run_payload,
    generate_sample_inputs,
    summary_report,
)


# --- folder + tool.json + pyproject checks ----------------------------------


@pytest.mark.asyncio
async def test_check_folder_structure_fails_when_missing_tool_json(
    tmp_pixie_root: Path,
) -> None:
    tool_dir = tmp_pixie_root / "tools" / "no-tool-json"
    tool_dir.mkdir(parents=True)
    check = await _check_folder_structure(tool_dir)
    assert check.status == "fail"


@pytest.mark.asyncio
async def test_check_folder_structure_passes_with_tool_json(
    tmp_pixie_root: Path,
) -> None:
    tool_dir = tmp_pixie_root / "tools" / "good"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.json").write_text("{}", encoding="utf-8")
    (tool_dir / "pyproject.toml").write_text(
        '[project]\nname = "good"\nversion = "0.1"\n', encoding="utf-8"
    )
    (tool_dir / "main.py").write_text("# tool", encoding="utf-8")
    check = await _check_folder_structure(tool_dir)
    assert check.status in {"pass", "warn"}


@pytest.mark.asyncio
async def test_check_tool_json_parses_invalid_json_fails(
    tmp_pixie_root: Path,
) -> None:
    tool_dir = tmp_pixie_root / "tools" / "broken-json"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.json").write_text("not-json{", encoding="utf-8")
    check, schema = await _check_tool_json_parses(tool_dir)
    assert check.status == "fail"
    assert schema is None


@pytest.mark.asyncio
async def test_check_tool_json_parses_valid_returns_schema(
    tmp_pixie_root: Path,
) -> None:
    tool_dir = tmp_pixie_root / "tools" / "ok-json"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.json").write_text(json.dumps({
        "id": "ok", "name": "OK",
        "inputs": [{"key": "x", "type": "number", "label": "X"}],
        "outputs": [{"key": "y", "type": "number", "label": "Y"}],
    }), encoding="utf-8")
    check, schema = await _check_tool_json_parses(tool_dir)
    assert check.status == "pass"
    assert schema is not None
    assert schema.id == "ok"


@pytest.mark.asyncio
async def test_check_pyproject_missing_warns(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "no-py"
    tool_dir.mkdir(parents=True)
    check = await _check_pyproject(tool_dir)
    assert check.status in {"fail", "warn"}


@pytest.mark.asyncio
async def test_check_pyproject_picks_up_dependencies(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "py"
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text(
        '[project]\n'
        'name = "p"\nversion = "0"\n'
        'dependencies = ["fastapi", "uvicorn", "python-dotenv"]\n',
        encoding="utf-8",
    )
    check = await _check_pyproject(tool_dir)
    assert check.status in {"pass", "warn"}


@pytest.mark.asyncio
async def test_check_venv_missing(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "no-venv"
    tool_dir.mkdir(parents=True)
    check = await _check_venv(tool_dir)
    assert check.status == "fail"


# --- schema coherence --------------------------------------------------------


@pytest.mark.asyncio
async def test_check_schemas_coherent_duplicate_keys_fails() -> None:
    schema = ToolSchema.model_validate({
        "id": "t", "name": "T",
        "inputs": [
            {"key": "x", "type": "text", "label": "X"},
            {"key": "x", "type": "text", "label": "X2"},
        ],
        "outputs": [{"key": "o", "type": "text", "label": "O"}],
    })
    check = await _check_schemas_coherent(schema)
    assert check.status == "fail"


@pytest.mark.asyncio
async def test_check_schemas_coherent_clean_schema_passes() -> None:
    schema = ToolSchema.model_validate({
        "id": "t", "name": "T",
        "inputs": [{"key": "x", "type": "text", "label": "X"}],
        "outputs": [{"key": "o", "type": "text", "label": "O"}],
    })
    check = await _check_schemas_coherent(schema)
    assert check.status == "pass"


# --- dep parsing -------------------------------------------------------------


@pytest.mark.parametrize(
    "dep,expected",
    [
        ("fastapi", "fastapi"),
        ("fastapi>=0.115", "fastapi"),
        ("fastapi[standard]", "fastapi"),
        ("fastapi==1.0;python_version>='3.12'", "fastapi"),
    ],
)
def test_extract_dep_names_normalises(dep: str, expected: str) -> None:
    names = _extract_dep_names([dep])
    assert expected in names


@pytest.mark.parametrize(
    "dep,non_pypi",
    [
        ("git+https://github.com/x/y", True),
        ("file:///path/to/wheel", True),
        ("../local/wheel", True),
        ("fastapi", False),
    ],
)
def test_looks_like_non_pypi(dep: str, non_pypi: bool) -> None:
    assert _looks_like_non_pypi(dep) is non_pypi


# --- output value checks per type -------------------------------------------


@pytest.mark.parametrize(
    "output_type,value,status",
    [
        ("text", "hello", "pass"),
        ("text", 42, "fail"),
        ("number", 3.14, "pass"),
        ("number", "no", "fail"),
        ("boolean", True, "pass"),
        ("boolean", 1, "pass"),  # truthy int accepted
        ("table", {"columns": ["a"], "rows": []}, "pass"),
        ("table", "not-a-table", "fail"),
        ("chart_line", {"x": [], "series": []}, "pass"),
        ("chart_line", {"x": []}, "fail"),  # missing required key
    ],
)
def test_check_output_value_per_type(output_type, value, status) -> None:
    spec = ToolSchema.model_validate({
        "id": "t", "name": "T",
        "inputs": [{"key": "x", "type": "text", "label": "X"}],
        "outputs": [{"key": "o", "type": output_type, "label": "O"}],
    }).outputs[0]
    out_status, _ = _check_output_value(spec, value)
    assert out_status == status


# --- compute_overall ---------------------------------------------------------


def test_compute_overall_fail_dominates() -> None:
    checks = [
        ValidationCheck(name="a", status="pass", message="ok"),
        ValidationCheck(name="b", status="fail", message="bad"),
    ]
    assert _compute_overall(checks) == "fail"


def test_compute_overall_warn_when_no_fail() -> None:
    checks = [
        ValidationCheck(name="a", status="pass", message="ok"),
        ValidationCheck(name="b", status="warn", message="slow"),
    ]
    assert _compute_overall(checks) == "warn"


def test_compute_overall_pass_when_all_pass() -> None:
    checks = [ValidationCheck(name="a", status="pass", message="ok")]
    assert _compute_overall(checks) == "pass"


# --- sample input generation -------------------------------------------------


def test_generate_sample_inputs_for_chat_layout_returns_messages() -> None:
    schema = ToolSchema.model_validate({
        "id": "c", "name": "Chat", "layout": "chat",
        "inputs": [{"key": "ignored", "type": "text", "label": "X"}],
        "outputs": [{"key": "y", "type": "text", "label": "Y"}],
    })
    payload = generate_sample_inputs(schema)
    assert "messages" in payload
    assert isinstance(payload["messages"], list)


@pytest.mark.parametrize(
    "input_type",
    ["text", "textarea", "number", "toggle", "checkbox", "date", "json"],
)
def test_sample_inputs_have_a_value_per_input_type(input_type: str) -> None:
    schema = ToolSchema.model_validate({
        "id": "t", "name": "T",
        "inputs": [{"key": "f", "type": input_type, "label": "F"}],
        "outputs": [{"key": "o", "type": "text", "label": "O"}],
    })
    sample = generate_sample_inputs(schema)
    assert "f" in sample


def test_build_sample_run_payload_includes_run_id_and_inputs() -> None:
    schema = ToolSchema.model_validate({
        "id": "t", "name": "T",
        "inputs": [{"key": "x", "type": "number", "label": "X", "default": 1}],
        "outputs": [{"key": "o", "type": "number", "label": "O"}],
    })
    payload = build_sample_run_payload(schema)
    assert "run_id" in payload
    assert payload["inputs"] == {"x": 1}
    # Backward-compat top-level shim:
    assert payload["x"] == 1


# --- schema diff -------------------------------------------------------------


def test_diff_schemas_detects_changed_key() -> None:
    disk = {"inputs": [{"key": "x", "type": "text"}]}
    live = {"inputs": [{"key": "x", "type": "number"}]}
    diffs = _diff_schemas(disk, live)
    assert diffs


def test_diff_schemas_no_diff_when_identical() -> None:
    disk = {"inputs": [{"key": "x", "type": "text"}]}
    live = {"inputs": [{"key": "x", "type": "text"}]}
    assert _diff_schemas(disk, live) == []


# --- clean shutdown check ----------------------------------------------------


def test_clean_shutdown_check_records_pass_on_clean_exit() -> None:
    check = _clean_shutdown_check(clean_exit=True, exit_code=0)
    assert check.status == "pass"


def test_clean_shutdown_check_records_fail_on_dirty_exit() -> None:
    check = _clean_shutdown_check(clean_exit=False, exit_code=-9)
    assert check.status in {"fail", "warn"}
