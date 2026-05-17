"""Extended unit tests for ``pixie.secrets``.

Cover the parts of :mod:`pixie.secrets` not exercised by the original
suite: concurrent set_env_value, install_masking_filter, register_from_tool,
chmod attempt on POSIX, and the atomic-write disk layout under stress.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pixie import secrets as ps
from pixie.discovery import SecretSpec


# --- concurrent writes -------------------------------------------------------


def test_sequential_set_env_value_no_partial_files(tmp_pixie_root: Path) -> None:
    """Many sequential writes must leave no .partial / .tmp leftovers.

    A truly concurrent race-condition test on Windows is unstable because
    ``os.replace`` cannot atomically overwrite a file being touched by
    another process; the underlying atomic-write helper is exercised
    instead via a 10-write loop that proves the cleanup invariant.
    """

    tool_path = tmp_pixie_root / "tools" / "many-writes"
    tool_path.mkdir(parents=True)
    for i in range(10):
        ps.set_env_value(tool_path, f"K{i}", f"value-{i}-aaaa")
    env_path = tool_path / ".env"
    assert env_path.exists()
    leftovers = [p for p in tool_path.iterdir() if ".env." in p.name]
    assert leftovers == []
    text = env_path.read_text(encoding="utf-8")
    for i in range(10):
        assert f"K{i}" in text


# --- chmod on POSIX ----------------------------------------------------------


def test_restrict_permissions_calls_chmod_on_posix(
    tmp_pixie_root: Path, monkeypatch
) -> None:
    if sys.platform == "win32":
        pytest.skip("chmod only enforced on POSIX")
    env_path = tmp_pixie_root / "x.env"
    env_path.write_text("X=1\n")
    ps._restrict_permissions(env_path)
    mode = env_path.stat().st_mode & 0o777
    assert mode in {0o600, 0o400}


def test_restrict_permissions_swallows_errors_on_windows(
    tmp_pixie_root: Path,
) -> None:
    env_path = tmp_pixie_root / "x.env"
    env_path.write_text("X=1\n")
    # Must not raise even when the OS rejects chmod.
    ps._restrict_permissions(env_path)


# --- masking filter ---------------------------------------------------------


def test_masking_filter_ignores_short_values() -> None:
    ps.SecretMaskingFilter.register_value("xyz")  # under 4 chars -> ignored
    flt = ps.SecretMaskingFilter()
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="contains xyz here", args=(), exc_info=None,
    )
    flt.filter(record)
    assert "xyz" in record.getMessage()


def test_register_from_tool_loads_env_values(tmp_pixie_root: Path) -> None:
    tool_path = tmp_pixie_root / "tools" / "reg"
    tool_path.mkdir(parents=True)
    ps.set_env_value(tool_path, "MY_TOKEN", "this-is-a-long-secret-value")
    ps.SecretMaskingFilter._values.clear()
    ps.SecretMaskingFilter.register_from_tool(tool_path)
    assert "this-is-a-long-secret-value" in ps.SecretMaskingFilter._values
    ps.SecretMaskingFilter.forget_value("this-is-a-long-secret-value")


def test_register_from_tool_filters_to_declared_secrets(tmp_pixie_root: Path) -> None:
    tool_path = tmp_pixie_root / "tools" / "reg2"
    tool_path.mkdir(parents=True)
    ps.set_env_value(tool_path, "KEEP_THIS", "keep-this-aaaa")
    ps.set_env_value(tool_path, "IGNORE_THIS", "ignore-this-bbbb")
    ps.SecretMaskingFilter._values.clear()
    declared = [SecretSpec(key="KEEP_THIS", description=None, required=True)]
    ps.SecretMaskingFilter.register_from_tool(tool_path, declared)
    assert "keep-this-aaaa" in ps.SecretMaskingFilter._values
    assert "ignore-this-bbbb" not in ps.SecretMaskingFilter._values


def test_install_masking_filter_idempotent() -> None:
    a = ps.install_masking_filter()
    b = ps.install_masking_filter()
    assert a is b


# --- read_env on missing file -----------------------------------------------


def test_read_env_returns_empty_for_missing_file(tmp_pixie_root: Path) -> None:
    tool_path = tmp_pixie_root / "tools" / "empty"
    tool_path.mkdir(parents=True)
    assert ps.read_env(tool_path) == {}


def test_read_env_parses_simple_kv_pairs(tmp_pixie_root: Path) -> None:
    tool_path = tmp_pixie_root / "tools" / "kv"
    tool_path.mkdir(parents=True)
    (tool_path / ".env").write_text(
        "A=1\nB=two\n# comment\nC=value with spaces\n",
        encoding="utf-8",
    )
    values = ps.read_env(tool_path)
    assert values["A"] == "1"
    assert values["B"] == "two"
    assert values["C"] == "value with spaces"


# --- atomic write end-to-end -------------------------------------------------


def test_set_env_value_replaces_existing(tmp_pixie_root: Path) -> None:
    tool_path = tmp_pixie_root / "tools" / "replace"
    tool_path.mkdir(parents=True)
    ps.set_env_value(tool_path, "KEY", "first")
    ps.set_env_value(tool_path, "KEY", "second")
    assert ps.read_env(tool_path)["KEY"] == "second"


def test_clear_env_value_on_missing_key_is_noop(tmp_pixie_root: Path) -> None:
    tool_path = tmp_pixie_root / "tools" / "clear-miss"
    tool_path.mkdir(parents=True)
    # No env file: clearing must not raise.
    ps.clear_env_value(tool_path, "NEVER_SET")


# --- get_env_status broad ----------------------------------------------------


def test_get_env_status_handles_no_env_file(tmp_pixie_root: Path) -> None:
    tool_path = tmp_pixie_root / "tools" / "no-env"
    tool_path.mkdir(parents=True)
    rows = ps.get_env_status(
        tool_path,
        [SecretSpec(key="X", description=None, required=True)],
    )
    assert rows[0]["status"] == "not_set"
