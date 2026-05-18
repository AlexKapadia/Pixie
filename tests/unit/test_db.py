"""Unit tests for ``pixie.db``.

Covers schema init (fresh + idempotent), the WAL / busy-timeout pragmas,
and CRUD round-trips for the four core tables (settings, runs,
tool_state, validation_reports).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pixie import db


@pytest.mark.asyncio
async def test_init_db_creates_all_tables(tmp_pixie_root: Path) -> None:
    """A fresh ``init_db`` must create every table the rest of Pixie uses."""

    db_path = tmp_pixie_root / "pixie.db"
    db.init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    names = {row[0] for row in rows}
    assert {"settings", "runs", "tool_state", "validation_reports"} <= names


@pytest.mark.asyncio
async def test_init_db_is_idempotent(tmp_pixie_root: Path) -> None:
    """Re-running ``init_db`` against an existing file must not raise."""

    db_path = tmp_pixie_root / "pixie.db"
    db.init_db(db_path)
    db.init_db(db_path)  # second call


@pytest.mark.asyncio
async def test_wal_and_busy_timeout_pragmas(tmp_pixie_root: Path) -> None:
    """WAL mode + busy_timeout pragmas must be active on every connection."""

    db_path = tmp_pixie_root / "pixie.db"
    db.init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        # journal_mode is persistent; a follow-up connection inherits it.
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    # The helper sets busy_timeout per-connection - verify via _open_connection.
    conn = db._open_connection(db_path)
    try:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_settings_round_trip(tmp_pixie_root: Path) -> None:
    """``set_setting`` then ``get_setting`` returns the same value."""

    db_path = tmp_pixie_root / "pixie.db"
    db.init_db(db_path)

    await db.set_setting(db_path, "theme", "dark")
    value = await db.get_setting(db_path, "theme")
    assert value == "dark"

    missing = await db.get_setting(db_path, "does-not-exist")
    assert missing is None


@pytest.mark.asyncio
async def test_runs_round_trip(tmp_pixie_root: Path) -> None:
    """A run row can be started, finished, and read back via ``list_runs``."""

    db_path = tmp_pixie_root / "pixie.db"
    db.init_db(db_path)

    run_id = "test-run-id"
    await db.record_run_start(
        db_path, run_id, "fixture-tool", {"x": 1, "y": 2}
    )
    await db.record_run_finish(db_path, run_id, {"result": 42})

    runs = await db.list_runs(db_path, "fixture-tool", limit=10)
    assert len(runs) == 1
    assert runs[0]["id"] == run_id
    assert runs[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_tool_state_round_trip(tmp_pixie_root: Path) -> None:
    """``set_tool_state`` writes both last-inputs and favourited flags."""

    db_path = tmp_pixie_root / "pixie.db"
    db.init_db(db_path)

    await db.set_tool_state(
        db_path, "fixture-tool", last_inputs={"x": 1}, favourited=True
    )
    state = await db.get_tool_state(db_path, "fixture-tool")
    assert state is not None
    assert bool(state["favourited"]) is True


@pytest.mark.asyncio
async def test_validation_report_round_trip(tmp_pixie_root: Path) -> None:
    """A report can be saved and the latest copy fetched back."""

    db_path = tmp_pixie_root / "pixie.db"
    db.init_db(db_path)

    report = {
        "tool_id": "fixture-tool",
        "tool_path": str(tmp_pixie_root / "tools" / "fixture-tool"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall": "pass",
        "checks": [],
        "sample_inputs": None,
        "sample_output": None,
        "spawn_log": None,
    }
    await db.save_validation_report(db_path, report)
    fetched = await db.latest_validation_report(db_path, "fixture-tool")
    assert fetched is not None
    assert fetched["overall"] == "pass"
