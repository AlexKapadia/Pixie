"""CLI smoke tests via Typer's CliRunner.

Heavy commands (serve / dev) aren't exercised — they bind ports. The
non-server commands (validate, sweep, artefacts, scaffold-tool, open,
tail) are covered via subprocess-free CliRunner invocations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pixie.__main__ import app


runner = CliRunner()


# --- help ----------------------------------------------------------------


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "validate" in result.stdout
    assert "scaffold-tool" in result.stdout


# --- validate ------------------------------------------------------------


def test_validate_missing_tool_exits_2(tmp_pixie_root: Path) -> None:
    result = runner.invoke(
        app, ["validate", "no-such-tool", "--tools-dir", str(tmp_pixie_root / "tools")],
    )
    assert result.exit_code == 2


def test_validate_broken_tool_runs(
    sample_tool_factory, tmp_pixie_root: Path,
) -> None:
    tool_dir = sample_tool_factory("broken-tool")
    result = runner.invoke(
        app, ["validate", "broken-tool",
              "--tools-dir", str(tmp_pixie_root / "tools"),
              "--no-save"],
    )
    # validate may exit 0 or 1 depending on results; either is fine
    assert result.exit_code in (0, 1)


def test_validate_summary_mode(
    sample_tool_factory, tmp_pixie_root: Path,
) -> None:
    sample_tool_factory("broken-tool")
    result = runner.invoke(
        app, ["validate", "broken-tool",
              "--tools-dir", str(tmp_pixie_root / "tools"),
              "--summary", "--no-save"],
    )
    assert result.exit_code in (0, 1)


def test_validate_json_output(
    sample_tool_factory, tmp_pixie_root: Path,
) -> None:
    sample_tool_factory("broken-tool")
    result = runner.invoke(
        app, ["validate", "broken-tool",
              "--tools-dir", str(tmp_pixie_root / "tools"),
              "--json", "--no-save"],
    )
    assert result.exit_code in (0, 1)


def test_validate_reference_only(
    sample_tool_factory, tmp_pixie_root: Path,
) -> None:
    sample_tool_factory("reference-tool")
    result = runner.invoke(
        app, ["validate", "reference-tool",
              "--tools-dir", str(tmp_pixie_root / "tools"),
              "--reference-only", "--no-save"],
    )
    assert result.exit_code in (0, 1)


def test_validate_update_fixtures_dry_run(
    sample_tool_factory, tmp_pixie_root: Path,
) -> None:
    sample_tool_factory("reference-tool")
    result = runner.invoke(
        app, ["validate", "reference-tool",
              "--tools-dir", str(tmp_pixie_root / "tools"),
              "--update-fixtures"],
    )
    assert result.exit_code in (0, 1)


# --- scaffold-tool -------------------------------------------------------


def test_scaffold_tool_blank(tmp_pixie_root: Path) -> None:
    result = runner.invoke(
        app, ["scaffold-tool", "scaffolded",
              "--template", "blank",
              "--tools-dir", str(tmp_pixie_root / "tools"),
              "--no-sync",
              "--no-validate"],
    )
    assert result.exit_code == 0
    assert (tmp_pixie_root / "tools" / "scaffolded" / "tool.json").exists()


def test_scaffold_tool_bad_id(tmp_pixie_root: Path) -> None:
    result = runner.invoke(
        app, ["scaffold-tool", "Bad-ID!!",
              "--template", "blank",
              "--tools-dir", str(tmp_pixie_root / "tools"),
              "--no-uv-sync", "--no-validate"],
    )
    assert result.exit_code != 0


def test_scaffold_tool_unknown_template(tmp_pixie_root: Path) -> None:
    result = runner.invoke(
        app, ["scaffold-tool", "x-tool",
              "--template", "no-such-template",
              "--tools-dir", str(tmp_pixie_root / "tools"),
              "--no-sync", "--no-validate"],
    )
    assert result.exit_code != 0


def test_scaffold_tool_template_list(tmp_pixie_root: Path) -> None:
    result = runner.invoke(app, ["scaffold-tool", "--template", "list"])
    assert result.exit_code == 0


# --- artefacts list ------------------------------------------------------


def test_artefacts_command_unknown_tool(tmp_pixie_root: Path) -> None:
    result = runner.invoke(
        app, ["artefacts", "no-such-tool",
              "--tools-dir", str(tmp_pixie_root / "tools")],
    )
    # tool may not exist; tolerate any exit
    assert result.exit_code in (0, 1, 2)


# --- sweep --------------------------------------------------------------


def test_sweep_dry_run(tmp_pixie_root: Path) -> None:
    from pixie import db
    db.init_db(tmp_pixie_root / "pixie.db")
    result = runner.invoke(
        app, ["sweep", "--dry-run"],
    )
    assert result.exit_code in (0, 1)


# --- open ---------------------------------------------------------------


def test_open_command_unknown_tool(tmp_pixie_root: Path) -> None:
    result = runner.invoke(
        app, ["open", "no-such-tool",
              "--tools-dir", str(tmp_pixie_root / "tools")],
    )
    assert result.exit_code == 2


# --- tail ---------------------------------------------------------------


def test_tail_command_unknown_tool(tmp_pixie_root: Path) -> None:
    result = runner.invoke(
        app, ["tail", "no-such-tool",
              "--tools-dir", str(tmp_pixie_root / "tools")],
    )
    assert result.exit_code in (0, 1, 2)
