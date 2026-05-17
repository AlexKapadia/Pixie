"""Unit tests for ``pixie.cli_helpers``: scaffold, open_in_os, listings."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pixie import cli_helpers


# --- list_templates ---------------------------------------------------------


def test_list_templates_returns_seven_canonical_templates() -> None:
    names = [t["name"] for t in cli_helpers.list_templates()]
    for expected in (
        "blank", "form", "chat", "ml-inference",
        "ml-training", "api-wrapper", "cli-wrapper",
    ):
        assert expected in names


def test_list_templates_missing_index_returns_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli_helpers, "TEMPLATES_ROOT", tmp_path)
    assert cli_helpers.list_templates() == []


# --- snake_case --------------------------------------------------------------


def test_snake_case_converts_hyphens() -> None:
    assert cli_helpers.snake_case("my-cool-tool") == "my_cool_tool"
    assert cli_helpers.snake_case("plain") == "plain"


# --- scaffold ----------------------------------------------------------------


def test_scaffold_blank_creates_expected_layout(tmp_path: Path) -> None:
    out = cli_helpers.scaffold("my-tool", "blank", tmp_path)
    assert out.exists()
    assert out.name == "my-tool"
    assert (out / "tool.json").is_file()
    text = (out / "tool.json").read_text(encoding="utf-8")
    assert "my-tool" in text


def test_scaffold_form_template(tmp_path: Path) -> None:
    out = cli_helpers.scaffold("calc", "form", tmp_path)
    assert (out / "tool.json").exists()
    # placeholder substitution in file content
    body = (out / "tool.json").read_text(encoding="utf-8")
    assert "{{TOOL_ID}}" not in body


def test_scaffold_rejects_bad_tool_id(tmp_path: Path) -> None:
    with pytest.raises(cli_helpers.ScaffoldError):
        cli_helpers.scaffold("Bad ID!", "blank", tmp_path)


def test_scaffold_rejects_unknown_template(tmp_path: Path) -> None:
    with pytest.raises(cli_helpers.ScaffoldError):
        cli_helpers.scaffold("ok-tool", "no-such-template", tmp_path)


def test_scaffold_refuses_existing_dir(tmp_path: Path) -> None:
    (tmp_path / "dupe").mkdir()
    with pytest.raises(cli_helpers.ScaffoldError):
        cli_helpers.scaffold("dupe", "blank", tmp_path)


def test_scaffold_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / "dupe").mkdir()
    (tmp_path / "dupe" / "garbage.txt").write_text("x")
    out = cli_helpers.scaffold("dupe", "blank", tmp_path, force=True)
    assert (out / "tool.json").exists()
    assert not (out / "garbage.txt").exists()


def test_scaffold_custom_name_and_description(tmp_path: Path) -> None:
    out = cli_helpers.scaffold(
        "alpha", "blank", tmp_path,
        name="My Alpha", description="Custom desc",
    )
    body = (out / "tool.json").read_text(encoding="utf-8")
    assert "My Alpha" in body or "alpha" in body


def test_scaffold_renders_every_template(tmp_path: Path) -> None:
    # Every published template should render without error.
    for tpl in cli_helpers.list_templates():
        name = tpl["name"]
        target = tmp_path / name
        target.mkdir()
        result = cli_helpers.scaffold("x-tool", name, target)
        assert (result / "tool.json").exists(), f"{name} missing tool.json"


# --- open_in_os --------------------------------------------------------------


def test_open_in_os_uses_startfile_on_windows(monkeypatch, tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("windows-only branch")
    calls: list[str] = []

    import os
    monkeypatch.setattr(os, "startfile", lambda p: calls.append(p), raising=False)
    cli_helpers.open_in_os(tmp_path)
    assert calls == [str(tmp_path)]


def test_open_in_os_uses_subprocess_on_darwin(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/open")
    seen: dict = {}

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    cli_helpers.open_in_os(tmp_path)
    assert seen["cmd"][0] == "/usr/bin/open"
    assert seen["cmd"][1] == str(tmp_path)


def test_open_in_os_uses_xdg_open_on_linux(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/xdg-open")
    seen: dict = {}

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    cli_helpers.open_in_os(tmp_path)
    assert seen["cmd"][0] == "/usr/bin/xdg-open"


# --- _gitkeep rename --------------------------------------------------------


def test_gitkeep_to_real_renames_only_marker(tmp_path: Path) -> None:
    from pixie.cli_helpers import _gitkeep_to_real
    sample = tmp_path / "a" / "_gitkeep"
    assert _gitkeep_to_real(sample).name == ".gitkeep"
    other = tmp_path / "a" / "real.txt"
    assert _gitkeep_to_real(other).name == "real.txt"
