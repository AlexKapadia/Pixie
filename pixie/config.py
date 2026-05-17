"""Pixie runtime configuration.

Single source of truth for filesystem paths, ports, and defaults. Values
load from environment variables prefixed with ``PIXIE_`` and from an
optional ``.env`` at the repo root. The ``host`` field is locked to a
loopback address; binding to anything else is refused by policy.
"""

from __future__ import annotations

import ipaddress
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Pixie host settings. Loaded from env + .env at the repo root."""

    model_config = SettingsConfigDict(
        env_prefix="PIXIE_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    port: int = 7860
    host: str = "127.0.0.1"

    repo_root: Path = REPO_ROOT
    tools_dir: Path = REPO_ROOT / "tools"
    db_path: Path = REPO_ROOT / "pixie.db"
    static_dir: Path = PACKAGE_ROOT / "static"
    templates_dir: Path = PACKAGE_ROOT / "templates"

    warm_keep_seconds: int = 300
    warm_keep_max: int = 5

    developer_mode: bool = False

    theme: Literal["light", "dark"] = "light"
    accent: str = "indigo"
    density: Literal["compact", "comfortable", "airy"] = "comfortable"

    # Artefact / output persistence (RESEARCH_output_persistence s12, s7).
    artefacts_root: Path = REPO_ROOT / "artefacts"
    max_artefact_bytes_per_run: int = 10 * 1024 * 1024 * 1024  # 10 GiB
    max_artefacts_per_run: int = 10_000
    artefacts_total_disk_cap_bytes: int | None = None
    dedup_artefacts: bool = False
    thumb_max_edge_px: int = 256
    thumb_workers: int = 2
    sweeper_interval_seconds: int = 6 * 60 * 60  # 6 hours
    soft_delete_retention_days: int = 7
    inline_output_max_bytes: int = 64 * 1024  # 64 KiB auto-spill threshold
    library_page_size: int = 50

    @field_validator("host")
    @classmethod
    def _host_must_be_loopback(cls, value: str) -> str:
        """Refuse anything that isn't a loopback address. Local-first by policy."""

        try:
            parsed = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(f"PIXIE_HOST must be a literal IP address, got {value!r}") from exc
        if not parsed.is_loopback:
            raise ValueError(
                f"PIXIE_HOST must be a loopback address (127.0.0.0/8 or ::1), got {value!r}"
            )
        return value


@cache
def get_settings() -> Settings:
    """Return the cached ``Settings`` instance for this process."""

    return Settings()


# TODO(phase-3a): wire `get_settings()` into the app factory's lifespan so
# routes can pull config via `request.app.state.settings`.
