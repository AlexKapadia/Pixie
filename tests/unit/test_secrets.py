"""Unit tests for ``pixie.secrets``.

Covers the atomic-write path (no ``.partial`` leftovers), the broad
``is_secret_key`` regex, the ``SecretMaskingFilter``, and the
declared-secret status view.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from pixie import secrets as pixie_secrets
from pixie.discovery import SecretSpec


@pytest.mark.parametrize(
    "name,expected",
    [
        ("OPENAI_API_KEY", True),
        ("GITHUB_TOKEN", True),
        ("USER_PASSWORD", True),
        ("Auth_Header", True),
        ("Bearer", True),
        ("JWT_PRIVATE_KEY", True),
        ("DB_CREDENTIAL", True),
        ("PORT", False),
        ("LOG_LEVEL", False),
        ("", False),
    ],
)
def test_is_secret_key_matches_broad_regex(name: str, expected: bool) -> None:
    """``is_secret_key`` flags anything that looks vaguely secret."""

    assert pixie_secrets.is_secret_key(name) is expected


def test_set_env_value_is_atomic(tmp_pixie_root: Path) -> None:
    """After ``set_env_value`` no temp file should remain in the tool dir."""

    tool_path = tmp_pixie_root / "tools" / "fixture"
    tool_path.mkdir(parents=True)

    pixie_secrets.set_env_value(tool_path, "OPENAI_API_KEY", "sk-test-1234567890")

    env_path = tool_path / ".env"
    assert env_path.exists()
    leftovers = [p for p in tool_path.iterdir() if p.name.startswith(".env.")]
    assert leftovers == [], f"atomic write left tmp files: {leftovers}"

    assert "OPENAI_API_KEY" in env_path.read_text(encoding="utf-8")


def test_clear_env_value_round_trip(tmp_pixie_root: Path) -> None:
    """Set then clear removes the key from the env file."""

    tool_path = tmp_pixie_root / "tools" / "fixture"
    tool_path.mkdir(parents=True)

    pixie_secrets.set_env_value(tool_path, "API_KEY", "abcdef-secret-value")
    pixie_secrets.clear_env_value(tool_path, "API_KEY")
    env_text = (tool_path / ".env").read_text(encoding="utf-8")
    assert "API_KEY" not in env_text


def test_secret_masking_filter_replaces_values(tmp_pixie_root: Path) -> None:
    """The masking filter substitutes registered values with ``***``."""

    pixie_secrets.SecretMaskingFilter.register_value("hunter2-totally-secret")
    flt = pixie_secrets.SecretMaskingFilter()

    record = logging.LogRecord(
        name="pixie.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="using key hunter2-totally-secret for auth",
        args=(),
        exc_info=None,
    )
    assert flt.filter(record) is True
    assert "hunter2-totally-secret" not in record.getMessage()
    assert "***" in record.getMessage()
    pixie_secrets.SecretMaskingFilter.forget_value("hunter2-totally-secret")


def test_secret_masking_filter_leaves_key_names_alone() -> None:
    """The key name is never substituted — only the value bytes."""

    pixie_secrets.SecretMaskingFilter.register_value("verybadpassword")
    flt = pixie_secrets.SecretMaskingFilter()
    record = logging.LogRecord(
        name="pixie.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="wrote secret USER_PASSWORD for fixture (15 bytes)",
        args=(),
        exc_info=None,
    )
    assert flt.filter(record) is True
    assert "USER_PASSWORD" in record.getMessage()
    pixie_secrets.SecretMaskingFilter.forget_value("verybadpassword")


def test_get_env_status_returns_no_values(tmp_pixie_root: Path) -> None:
    """The status view exposes set / not_set only, never raw values."""

    tool_path = tmp_pixie_root / "tools" / "fixture"
    tool_path.mkdir(parents=True)
    pixie_secrets.set_env_value(tool_path, "REAL_KEY", "actual-secret-value")

    declared = [
        SecretSpec(key="REAL_KEY", description="d", required=True),
        SecretSpec(key="MISSING_KEY", description=None, required=False),
    ]
    rows = pixie_secrets.get_env_status(tool_path, declared)
    statuses = {row["key"]: row["status"] for row in rows}
    assert statuses == {"REAL_KEY": "set", "MISSING_KEY": "not_set"}
    for row in rows:
        assert "value" not in row
