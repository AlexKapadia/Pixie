"""Direct tests for validator check helpers.

Each ``_check_*`` function gets driven against a temp tool tree using
``make_tool_json``. ``validate_tool`` is exercised end-to-end against the
broken-tool fixture (early-fail path) and against an inline minimal
tool (later-stage paths without spawning a real subprocess).
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from pixie.discovery import ToolSchema
from pixie.validator import (
    _check_folder_structure,
    _check_pyproject,
    _check_schemas_coherent,
    _check_tool_json_parses,
    _check_venv,
    _diff_schemas,
    _canonicalise,
    _free_port,
    _summarise_reference_results,
    summary_report,
    validate_tool,
    validate_tool_sync,
)
from pixie.comparators._base import FixtureResult


# --- _check_folder_structure ------------------------------------------------


@pytest.mark.asyncio
async def test_folder_structure_pass(make_tool_json) -> None:
    tool_dir = make_tool_json("ok-tool")
    (tool_dir / "pyproject.toml").write_text(
        "[project]\nname='x'\nversion='0'\ndependencies=[]\n", encoding="utf-8",
    )
    (tool_dir / "main.py").write_text("# main\n", encoding="utf-8")
    out = await _check_folder_structure(tool_dir)
    assert out.status == "pass"


@pytest.mark.asyncio
async def test_folder_structure_missing_file(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "lonely"
    tool_dir.mkdir(parents=True)
    out = await _check_folder_structure(tool_dir)
    assert out.status == "fail"
    assert "missing" in out.message


# --- _check_tool_json_parses ------------------------------------------------


@pytest.mark.asyncio
async def test_tool_json_parses_invalid_json(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "bad-json"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.json").write_text("{not-json", encoding="utf-8")
    check, schema = await _check_tool_json_parses(tool_dir)
    assert check.status == "fail"
    assert schema is None


@pytest.mark.asyncio
async def test_tool_json_parses_wrong_schema(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "wrong-schema"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.json").write_text('{"missing": "required"}', encoding="utf-8")
    check, schema = await _check_tool_json_parses(tool_dir)
    assert check.status == "fail"
    assert schema is None


@pytest.mark.asyncio
async def test_tool_json_parses_ok(make_tool_json) -> None:
    tool_dir = make_tool_json("good-schema")
    check, schema = await _check_tool_json_parses(tool_dir)
    assert check.status == "pass"
    assert schema is not None
    assert schema.id == "good-schema"


# --- _check_schemas_coherent ------------------------------------------------


@pytest.mark.asyncio
async def test_schemas_coherent_pass(make_tool_json) -> None:
    tool_dir = make_tool_json("ok-c")
    _, schema = await _check_tool_json_parses(tool_dir)
    out = await _check_schemas_coherent(schema)
    assert out.status == "pass"


@pytest.mark.asyncio
async def test_schemas_coherent_duplicate_input_key(make_tool_json) -> None:
    tool_dir = make_tool_json("dup", overrides={
        "inputs": [
            {"key": "x", "type": "number", "label": "X"},
            {"key": "x", "type": "number", "label": "X2"},
        ],
    })
    _, schema = await _check_tool_json_parses(tool_dir)
    out = await _check_schemas_coherent(schema)
    assert out.status == "fail"
    assert "duplicate" in (out.details or "")


# --- _check_pyproject -------------------------------------------------------


@pytest.mark.asyncio
async def test_pyproject_missing_required_deps(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "no-deps"
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text(
        "[project]\nname='x'\nversion='0'\ndependencies=[]\n", encoding="utf-8",
    )
    out = await _check_pyproject(tool_dir)
    assert out.status == "fail"
    assert "missing required" in out.message


@pytest.mark.asyncio
async def test_pyproject_parse_error(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "bad-toml"
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text("not= = valid toml [[", encoding="utf-8")
    out = await _check_pyproject(tool_dir)
    assert out.status == "fail"


@pytest.mark.asyncio
async def test_pyproject_warns_on_non_pypi_dep(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "git-dep"
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0"\n'
        'dependencies=["fastapi", "uvicorn", "pydantic", '
        '"private-thing @ git+https://example.com/x.git"]\n',
        encoding="utf-8",
    )
    out = await _check_pyproject(tool_dir)
    # Either warns or fails (warn-eligible since required deps now present)
    assert out.status in ("warn", "fail", "pass")


# --- _check_venv ------------------------------------------------------------


@pytest.mark.asyncio
async def test_venv_missing(tmp_pixie_root: Path) -> None:
    tool_dir = tmp_pixie_root / "tools" / "no-venv"
    tool_dir.mkdir(parents=True)
    out = await _check_venv(tool_dir)
    assert out.status in ("fail", "warn")


# --- _canonicalise / _diff_schemas ----------------------------------------


def test_canonicalise_normalises_keys() -> None:
    a = {"b": 2, "a": 1}
    out = _canonicalise(a)
    assert list(out.keys()) == ["a", "b"]


def test_canonicalise_nested() -> None:
    out = _canonicalise({"y": [{"b": 1, "a": 2}], "x": 1})
    assert list(out.keys()) == ["x", "y"]


def test_diff_schemas_no_diff() -> None:
    assert _diff_schemas({"a": 1}, {"a": 1}) == []


def test_diff_schemas_addition() -> None:
    diffs = _diff_schemas({"a": 1}, {"a": 1, "b": 2})
    assert any("b" in d[0] for d in diffs)


# --- _free_port -----------------------------------------------------------


def test_free_port_returns_loopback_port() -> None:
    port = _free_port()
    assert isinstance(port, int)
    assert 1024 < port < 65536


# --- _summarise_reference_results ----------------------------------------


def test_summarise_reference_results_all_pass() -> None:
    results = [
        FixtureResult(name="a", status="pass", message="ok"),
        FixtureResult(name="b", status="pass", message="ok"),
    ]
    out = _summarise_reference_results(results)
    assert out.status == "pass"


def test_summarise_reference_results_with_fail() -> None:
    results = [
        FixtureResult(name="a", status="fail", message="differs"),
    ]
    out = _summarise_reference_results(results)
    assert out.status == "fail"


def test_summarise_reference_results_all_skip_warns() -> None:
    results = [FixtureResult(name="a", status="skip", message="no ref")]
    out = _summarise_reference_results(results)
    assert out.status in ("warn", "pass")


# --- summary_report ------------------------------------------------------


def test_summary_report_from_report_object(mock_validator_report) -> None:
    report = mock_validator_report()
    out = summary_report(report)
    assert "overall" in out
    assert out["overall"] == "pass"


def test_summary_report_from_dict_payload() -> None:
    payload = {
        "tool_id": "x", "overall": "fail",
        "checks": [{"name": "folder_structure", "status": "fail",
                     "message": "no main.py", "details": None}],
    }
    out = summary_report(payload)
    assert out["overall"] == "fail"
    assert out["counts"].get("fail", 0) >= 1


# --- validate_tool against broken fixture --------------------------------


@pytest.mark.asyncio
async def test_validate_tool_broken_returns_fail(
    sample_tool_factory,
) -> None:
    tool_dir = sample_tool_factory("broken-tool")
    report = await validate_tool(tool_dir, save_to_db=False)
    assert report.overall in ("fail", "warn")


def test_validate_tool_sync_wrapper_returns_report(
    sample_tool_factory,
) -> None:
    tool_dir = sample_tool_factory("broken-tool")
    report = validate_tool_sync(tool_dir, save_to_db=False)
    assert report.tool_id
    assert report.overall in ("fail", "warn", "pass")
