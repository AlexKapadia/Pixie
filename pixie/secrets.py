"""Per-tool secret handling.

Reads and writes ``tools/<id>/.env``. Secret values never leave the
process boundary except by being injected into a child's ``env=``
mapping at ``Popen`` time. The UI shows ``set`` / ``not set`` and a
``Replace`` action only — never ``View``. Secret values are never
logged, echoed back to the browser, or stored in ``pixie.db``.

The atomic-write recipe (mkstemp -> fsync -> os.replace) follows the
research dossier (RESEARCH_security_process.md s6). POSIX hosts get
``chmod 600`` on the resulting ``.env``; Windows relies on the user
profile ACL.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from dotenv import dotenv_values

from pixie.discovery import SecretSpec

logger = logging.getLogger("pixie.secrets")

# Broad pattern from DECISIONS s17. Matches anywhere in the identifier so a
# key like USER_PASSWORD or GITHUB_AUTH_TOKEN is detected.
_SECRET_KEY_PATTERN = re.compile(
    r"password|secret|token|api[_-]?key|auth|bearer|jwt|credential",
    re.IGNORECASE,
)


def is_secret_key(name: str) -> bool:
    """Return True if ``name`` looks like a secret-bearing identifier."""

    if not name:
        return False
    return bool(_SECRET_KEY_PATTERN.search(name))


def _env_path(tool_path: Path) -> Path:
    return tool_path / ".env"


def read_env(tool_path: Path) -> dict[str, str]:
    """Return the dict of values currently in ``tools/<id>/.env``.

    Returns an empty dict if the file does not exist. Nones become empty
    strings so callers can rely on ``str`` semantics.
    """

    env_path = _env_path(tool_path)
    if not env_path.exists():
        return {}
    return {k: (v or "") for k, v in dotenv_values(env_path).items()}


def _serialise(values: dict[str, str]) -> str:
    """Render a sorted ``KEY="value"`` block. Values are quoted; embedded
    backslashes and double quotes are escaped so the round-trip via
    ``python-dotenv`` is exact.
    """

    lines: list[str] = []
    for key in sorted(values):
        raw = values[key]
        escaped = raw.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}="{escaped}"')
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _atomic_write(env_path: Path, payload: str) -> None:
    """Write ``payload`` to ``env_path`` atomically: tmp in same dir,
    fsync, ``os.replace``. Survives crashes mid-write because the rename
    is atomic on POSIX and Windows when source and target share a volume.
    """

    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".env.", suffix=".tmp", dir=str(env_path.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, env_path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        raise
    _restrict_permissions(env_path)


def _restrict_permissions(path: Path) -> None:
    """POSIX: chmod 600. Windows: best-effort no-op (ACL-based)."""

    if sys.platform == "win32":
        return
    with contextlib.suppress(PermissionError, OSError):
        os.chmod(path, 0o600)


def set_env_value(tool_path: Path, key: str, value: str) -> None:
    """Write ``key=value`` into ``tools/<id>/.env`` atomically.

    The value is never logged — only the key name. Callers must validate
    the key is a non-empty identifier before invoking.
    """

    if not key or not key.strip():
        raise ValueError("secret key must be non-empty")
    current = read_env(tool_path)
    current[key] = value
    _atomic_write(_env_path(tool_path), _serialise(current))
    logger.info("wrote secret %s for %s (%d bytes)", key, tool_path.name, len(value))
    SecretMaskingFilter.register_value(value)


def clear_env_value(tool_path: Path, key: str) -> None:
    """Remove ``key`` from ``tools/<id>/.env`` atomically. No-op if absent."""

    current = read_env(tool_path)
    if key not in current:
        return
    old_value = current.pop(key)
    _atomic_write(_env_path(tool_path), _serialise(current))
    logger.info("cleared secret %s for %s", key, tool_path.name)
    SecretMaskingFilter.forget_value(old_value)


def get_env_status(
    tool_path: Path, declared_secrets: Iterable[SecretSpec]
) -> list[dict[str, Any]]:
    """Return one row per declared secret with ``status`` set / not_set.

    The returned dict never contains the actual value — only metadata
    suitable for rendering the secrets panel.
    """

    present = read_env(tool_path)
    rows: list[dict[str, Any]] = []
    for spec in declared_secrets:
        has_value = bool(present.get(spec.key))
        rows.append(
            {
                "key": spec.key,
                "description": spec.description,
                "required": bool(spec.required),
                "status": "set" if has_value else "not_set",
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Logging filter
# ---------------------------------------------------------------------------


class SecretMaskingFilter(logging.Filter):
    """Logging filter that replaces known secret values with ``***``.

    The set of values is populated lazily: on Pixie startup the lifespan
    scans every tool's ``.env`` and feeds the values via
    :meth:`register_value`. Subsequent saves through
    :func:`set_env_value` register new values automatically.

    Values shorter than 4 characters are ignored to avoid clobbering
    normal log text.
    """

    _values: set[str] = set()

    @classmethod
    def register_value(cls, value: str) -> None:
        if value and len(value) >= 4:
            cls._values.add(value)

    @classmethod
    def forget_value(cls, value: str) -> None:
        cls._values.discard(value)

    @classmethod
    def register_from_tool(
        cls, tool_path: Path, declared_secrets: Iterable[SecretSpec] | None = None
    ) -> None:
        """Load every value from the tool's .env into the mask set."""

        values = read_env(tool_path)
        if declared_secrets is not None:
            for spec in declared_secrets:
                value = values.get(spec.key)
                if value:
                    cls.register_value(value)
            return
        for key, value in values.items():
            if value:
                cls.register_value(value)

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._values:
            return True
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — never break logging
            return True
        if not message:
            return True
        masked = message
        for value in self._values:
            if value and value in masked:
                masked = masked.replace(value, "***")
        if masked != message:
            record.msg = masked
            record.args = ()
        return True


def install_masking_filter() -> SecretMaskingFilter:
    """Install the masking filter on the root logger. Returns the instance."""

    root = logging.getLogger()
    for existing in root.filters:
        if isinstance(existing, SecretMaskingFilter):
            return existing
    instance = SecretMaskingFilter()
    root.addFilter(instance)
    for handler in root.handlers:
        handler.addFilter(instance)
    return instance
