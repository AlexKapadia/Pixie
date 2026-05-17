"""Integration tests for check #12 (``reference_fixtures_match``).

Pass-case, fail-case, skip-case via the real validator pipeline. Also
exercises the HTTP endpoints ``GET /api/tools/{id}/reference-fixtures``
and ``POST /api/tools/{id}/reference-check`` end-to-end.

Reuses ``staged_example_tool`` patterns from this directory's conftest
to copy the example tool's venv into the test-staged fixture tool —
that's the cheapest way to get a runnable Python interpreter without
calling ``uv sync`` (forbidden per RULES.md §3).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import httpx
import pytest

from pixie.validator import validate_tool_sync


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TOOL_VENV = REPO_ROOT / "tools" / "example-compound-interest" / ".venv"


def _venv_python(tool_path: Path) -> Path:
    if sys.platform == "win32":
        return tool_path / ".venv" / "Scripts" / "python.exe"
    return tool_path / ".venv" / "bin" / "python"


def _stage_reference_tool(sample_tool_factory, as_id: str = "reference-tool") -> Path:
    """Copy the reference-tool fixture into the scratch root with a venv."""

    if not EXAMPLE_TOOL_VENV.exists():
        pytest.skip(
            "example-compound-interest/.venv missing - "
            "run `cd tools/example-compound-interest && uv sync` first"
        )
    tool_path = sample_tool_factory("reference-tool", as_id=as_id)
    shutil.copytree(EXAMPLE_TOOL_VENV, tool_path / ".venv", symlinks=True)
    return tool_path


def test_reference_check_pass_case(sample_tool_factory) -> None:
    tool_path = _stage_reference_tool(sample_tool_factory)
    report = validate_tool_sync(tool_path, save_to_db=False)
    by_name = {c.name: c for c in report.checks}
    check = by_name["reference_fixtures_match"]
    assert check.status == "pass", f"expected pass, got {check.status}: {check.message}\n{check.details}"
    assert "2 fixture" in check.message
    # Overall must be pass too (no other check should regress).
    assert report.overall in {"pass", "warn"}, f"overall={report.overall}: {[(c.name, c.status) for c in report.checks]}"


def test_reference_check_skip_when_no_reference_folder(sample_tool_factory) -> None:
    """A tool without reference/ must produce a skip, not fail."""

    tool_path = _stage_reference_tool(sample_tool_factory, as_id="reference-tool-noref")
    shutil.rmtree(tool_path / "reference")
    report = validate_tool_sync(tool_path, save_to_db=False)
    by_name = {c.name: c for c in report.checks}
    check = by_name["reference_fixtures_match"]
    assert check.status == "skip"
    assert "no reference" in check.message


def test_reference_check_fail_case_via_broken_expected(sample_tool_factory) -> None:
    """Rewrite the basic fixture's expected_outputs to a wrong value.

    The tool itself is unchanged; only the fixture is wrong, which is
    enough to make check #12 fail with a populated details block.
    """

    tool_path = _stage_reference_tool(sample_tool_factory, as_id="reference-tool-broken")
    fixture = tool_path / "reference" / "fixture_basic.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    data["expected_outputs"]["result"] = 99.0  # sqrt(4) != 99
    fixture.write_text(json.dumps(data, indent=2), encoding="utf-8")

    report = validate_tool_sync(tool_path, save_to_db=False)
    by_name = {c.name: c for c in report.checks}
    check = by_name["reference_fixtures_match"]
    assert check.status == "fail"
    assert check.details and "rtol_exceeded" in check.details
    assert report.overall == "fail"


def test_reference_only_mode_skips_intermediate_checks(sample_tool_factory) -> None:
    tool_path = _stage_reference_tool(sample_tool_factory, as_id="reference-tool-refonly")
    report = validate_tool_sync(tool_path, save_to_db=False, reference_only=True)
    by_name = {c.name: c for c in report.checks}
    for name in ("sample_run_succeeds", "output_conforms", "streaming_check"):
        assert by_name[name].status == "skip"
    assert by_name["reference_fixtures_match"].status == "pass"


def test_reference_check_fixture_filter(sample_tool_factory) -> None:
    tool_path = _stage_reference_tool(sample_tool_factory, as_id="reference-tool-filter")
    report = validate_tool_sync(
        tool_path, save_to_db=False,
        reference_only=True, fixture_filter=["basic"],
    )
    by_name = {c.name: c for c in report.checks}
    check = by_name["reference_fixtures_match"]
    assert check.status == "pass"
    assert "1 fixture" in check.message


def test_reference_check_invalid_tolerance_yaml(sample_tool_factory) -> None:
    tool_path = _stage_reference_tool(sample_tool_factory, as_id="reference-tool-badyaml")
    (tool_path / "reference" / "tolerance.yaml").write_text(
        "defaults:\n  number: { rtol: not-a-number }\n",
        encoding="utf-8",
    )
    report = validate_tool_sync(tool_path, save_to_db=False)
    check = next(c for c in report.checks if c.name == "reference_fixtures_match")
    assert check.status == "fail"
    assert "invalid tolerance.yaml" in check.message


async def test_http_reference_fixtures_endpoint(
    sample_tool_factory, pixie_server: str,
) -> None:
    """``GET /api/tools/{id}/reference-fixtures`` lists fixtures and tags."""

    _stage_reference_tool(sample_tool_factory)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{pixie_server}/api/tools/reference-tool/reference-fixtures",
            timeout=10.0,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["has_reference_folder"] is True
    assert body["count"] == 2
    names = {entry["filename"] for entry in body["fixtures"]}
    assert names == {"fixture_basic.json", "fixture_tolerance.json"}


async def test_http_reference_check_endpoint_pass(
    sample_tool_factory, pixie_server: str,
) -> None:
    """``POST /api/tools/{id}/reference-check`` returns a pass report."""

    _stage_reference_tool(sample_tool_factory)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{pixie_server}/api/tools/reference-tool/reference-check",
            json={},
            timeout=60.0,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["check"]["status"] == "pass"
    assert "2 fixture" in body["check"]["message"]
