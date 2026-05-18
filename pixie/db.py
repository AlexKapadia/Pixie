"""SQLite schema and helpers for Pixie.

Owns the connection to ``pixie.db`` at the repo root, applies the
schema on startup, and exposes thin typed helpers for settings,
run history, last-inputs cache, validation-report persistence,
artefact store, workspaces, tool tags, and validate-job tracking.
Pixie uses stdlib ``sqlite3`` only — no ORM.

Tables: ``settings``, ``runs``, ``tool_state``, ``validation_reports``,
``artefacts``, ``workspaces``, ``tool_workspaces``, ``tool_tags``,
``validate_jobs``. Migrations are inline DDL guarded by
``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` /
``try ... except sqlite3.OperationalError`` for column additions so
``init_db`` is safe to re-run on any prior database.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger("pixie.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    inputs_json TEXT NOT NULL,
    outputs_json TEXT,
    error_text TEXT,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_tool ON runs(tool_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS tool_state (
    tool_id TEXT PRIMARY KEY,
    last_inputs_json TEXT,
    favourited INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER
);

CREATE TABLE IF NOT EXISTS validation_reports (
    tool_id TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    overall TEXT NOT NULL,
    report_json TEXT NOT NULL,
    PRIMARY KEY (tool_id, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_validation_latest
    ON validation_reports(tool_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS artefacts (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    output_key TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    starred INTEGER NOT NULL DEFAULT 0,
    label TEXT,
    tags TEXT,
    thumb_path TEXT,
    deleted_at TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_artefacts_run ON artefacts(run_id);
CREATE INDEX IF NOT EXISTS idx_artefacts_tool
    ON artefacts(tool_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artefacts_starred
    ON artefacts(starred) WHERE starred = 1;
CREATE INDEX IF NOT EXISTS idx_artefacts_deleted
    ON artefacts(deleted_at);

CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    colour TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    collapsed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_workspaces (
    tool_id TEXT NOT NULL,
    workspace_id INTEGER NOT NULL,
    added_at TIMESTAMP NOT NULL,
    PRIMARY KEY (tool_id, workspace_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tool_tags (
    tool_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (tool_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_tool_tags_tag ON tool_tags(tag);

CREATE TABLE IF NOT EXISTS validate_jobs (
    id TEXT PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    total INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    warned INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS archive_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_id TEXT NOT NULL,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT CHECK(source IN ('cli','api','test'))
);

CREATE INDEX IF NOT EXISTS idx_archive_log_tool_id
    ON archive_log(tool_id);
"""

# Indexes whose columns exist on the base SCHEMA (safe to create early).
# Indexes that depend on migrated columns live in
# ``_POST_MIGRATION_INDEXES`` so they only run after the ALTERs have applied.
_BASE_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_validate_jobs_status "
    "ON validate_jobs(status)",
    "CREATE INDEX IF NOT EXISTS idx_artefacts_label ON artefacts(label)",
)

# tool_state column additions applied in order. Re-adds fail with
# ``OperationalError`` which we swallow — that is the idempotency contract.
_TOOL_STATE_COLUMN_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("overrides_json", "TEXT"),
    ("archived", "INTEGER NOT NULL DEFAULT 0"),
    ("pinned", "INTEGER NOT NULL DEFAULT 0"),
    ("pinned_warm", "INTEGER NOT NULL DEFAULT 0"),
    ("discovery_hash", "TEXT"),
    ("run_count_total", "INTEGER NOT NULL DEFAULT 0"),
    ("disk_bytes", "INTEGER"),
    ("last_disk_audit", "TIMESTAMP"),
    ("last_run_at", "TIMESTAMP"),
    ("default_warm_keep_seconds", "INTEGER"),
    ("pinned_at", "TIMESTAMP"),
    ("archived_at", "TIMESTAMP"),
    ("colour", "TEXT"),
    ("sort_order_in_workspace_json", "TEXT"),
)

# Additions on the runs table (artefact persistence + labels/stars).
_RUNS_COLUMN_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("starred", "INTEGER NOT NULL DEFAULT 0"),
    ("label", "TEXT"),
    ("total_artefact_bytes", "INTEGER NOT NULL DEFAULT 0"),
    ("meta_json", "TEXT"),
)

# Additional indexes that depend on migrated columns existing first.
_POST_MIGRATION_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_tool_state_archived "
    "ON tool_state(archived)",
    "CREATE INDEX IF NOT EXISTS idx_tool_state_pinned "
    "ON tool_state(pinned)",
    # Partial indexes on runs.starred / runs.label (added by
    # _RUNS_COLUMN_MIGRATIONS above). Partial form keeps the index tiny
    # since the vast majority of runs are not starred / labelled.
    "CREATE INDEX IF NOT EXISTS idx_runs_starred "
    "ON runs(starred) WHERE starred = 1",
    "CREATE INDEX IF NOT EXISTS idx_runs_label "
    "ON runs(label) WHERE label IS NOT NULL",
)


def _open_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path,
        isolation_level=None,
        check_same_thread=False,
        timeout=5.0,
    )
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = _open_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def connect(path: Path | str) -> sqlite3.Connection:
    """Public helper: open a pixie.db connection with the right PRAGMAs.

    Always enables ``PRAGMA foreign_keys = ON`` (sqlite3 defaults to OFF, so
    any code path that opens its own connection MUST go through this helper
    to keep ON DELETE CASCADE semantics intact). Mirrors
    :func:`_open_connection` settings so external callers behave identically
    to the internal context manager. Caller owns ``close()``.
    """

    return _open_connection(Path(path))


def _safe_alter(conn: sqlite3.Connection, statement: str) -> None:
    """Run an ALTER / CREATE INDEX swallowing the duplicate-column error.

    SQLite raises ``OperationalError`` for both "duplicate column name"
    and other migration shapes that are already applied; the message is
    the only way to discriminate. We swallow only the duplicate-shape
    errors and re-raise anything else.
    """

    try:
        conn.execute(statement)
    except sqlite3.OperationalError as exc:
        text = str(exc).lower()
        if "duplicate column" in text or "already exists" in text:
            return
        raise


def init_db(db_path: Path) -> None:
    """Create tables, columns, and indexes (idempotent).

    Re-runnable on any prior schema generation. New tables come from the
    ``SCHEMA`` script; new columns are applied via ``ALTER TABLE`` and the
    duplicate-column error is swallowed so re-running on an already-migrated
    database is a no-op. New indexes are guarded by ``IF NOT EXISTS``.
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for column, ddl in _TOOL_STATE_COLUMN_MIGRATIONS:
            _safe_alter(conn, f"ALTER TABLE tool_state ADD COLUMN {column} {ddl}")
        for column, ddl in _RUNS_COLUMN_MIGRATIONS:
            _safe_alter(conn, f"ALTER TABLE runs ADD COLUMN {column} {ddl}")
        for statement in _BASE_INDEXES:
            _safe_alter(conn, statement)
        for statement in _POST_MIGRATION_INDEXES:
            _safe_alter(conn, statement)
        # Rebuild artefacts table to add ON DELETE CASCADE + UNIQUE(rel_path)
        # if not already in that shape. Idempotent: short-circuits when the
        # current FK is already cascading.
        _rebuild_artefacts_with_cascade_fk(conn)
    logger.info("sqlite schema initialised at %s", db_path)


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all idempotent schema migrations on an open connection.

    Lets external callers (smoke tests, ad-hoc scripts) run the same
    migration sequence ``init_db`` uses without going through the
    file-path entry point. Re-runnable; each step short-circuits when
    already applied.
    """

    conn.executescript(SCHEMA)
    for column, ddl in _TOOL_STATE_COLUMN_MIGRATIONS:
        _safe_alter(conn, f"ALTER TABLE tool_state ADD COLUMN {column} {ddl}")
    for column, ddl in _RUNS_COLUMN_MIGRATIONS:
        _safe_alter(conn, f"ALTER TABLE runs ADD COLUMN {column} {ddl}")
    for statement in _BASE_INDEXES:
        _safe_alter(conn, statement)
    for statement in _POST_MIGRATION_INDEXES:
        _safe_alter(conn, statement)
    _rebuild_artefacts_with_cascade_fk(conn)


# ---------------------------------------------------------------------------
# Artefacts table rebuild (FK CASCADE + UNIQUE rel_path)
# ---------------------------------------------------------------------------


# Column order MUST match SCHEMA's CREATE TABLE artefacts above. Used both
# in the rebuild CREATE TABLE and in the INSERT ... SELECT statement so we
# don't rely on positional ordering across SQLite versions.
_ARTEFACTS_COLUMNS: tuple[str, ...] = (
    "id", "run_id", "tool_id", "output_key", "rel_path", "filename",
    "mime", "size_bytes", "sha256", "created_at", "starred", "label",
    "tags", "thumb_path", "deleted_at",
)


def _artefacts_fk_is_cascade(conn: sqlite3.Connection) -> bool:
    """True iff artefacts.run_id FK already has ON DELETE CASCADE.

    ``PRAGMA foreign_key_list`` returns rows like
    ``(id, seq, table, from, to, on_update, on_delete, match)``. We look
    for the row whose ``from`` column is ``run_id`` and whose
    ``on_delete`` is ``CASCADE``.
    """

    try:
        rows = conn.execute("PRAGMA foreign_key_list(artefacts)").fetchall()
    except sqlite3.OperationalError:
        return False
    for row in rows:
        # row is a sqlite3.Row when row_factory is set (default in this
        # module). Access by name for clarity.
        try:
            from_col = row["from"]
            on_delete = row["on_delete"]
        except (IndexError, KeyError):
            # Fallback for plain tuples.
            from_col = row[3]
            on_delete = row[6]
        if from_col == "run_id" and (on_delete or "").upper() == "CASCADE":
            return True
    return False


def _artefacts_has_unique_rel_path(conn: sqlite3.Connection) -> bool:
    """True iff artefacts.rel_path is covered by a UNIQUE index."""

    try:
        idx_rows = conn.execute(
            "PRAGMA index_list(artefacts)"
        ).fetchall()
    except sqlite3.OperationalError:
        return False
    for idx in idx_rows:
        # PRAGMA index_list: (seq, name, unique, origin, partial)
        try:
            name = idx["name"]
            is_unique = idx["unique"]
        except (IndexError, KeyError):
            name = idx[1]
            is_unique = idx[2]
        if not is_unique:
            continue
        info = conn.execute(f"PRAGMA index_info({name})").fetchall()
        # index_info: (seqno, cid, name)
        cols: list[str] = []
        for info_row in info:
            try:
                cols.append(info_row["name"])
            except (IndexError, KeyError):
                cols.append(info_row[2])
        if cols == ["rel_path"]:
            return True
    return False


def _rebuild_artefacts_with_cascade_fk(conn: sqlite3.Connection) -> None:
    """Rebuild ``artefacts`` to add ON DELETE CASCADE + UNIQUE(rel_path).

    Idempotent: short-circuits when both the cascading FK and the
    UNIQUE constraint are already present. Runs inside an exclusive
    transaction so a crash mid-rebuild leaves the original table intact.

    Steps:
        1. Begin transaction (DEFERRED).
        2. Purge orphan rows whose run_id no longer points at runs.
        3. Dedupe duplicate rel_path rows keeping the most recent (max id).
        4. Create ``artefacts_new`` mirroring the current schema PLUS
           ``ON DELETE CASCADE`` on the run_id FK and ``UNIQUE(rel_path)``.
        5. Copy rows over.
        6. Drop old table, rename new one into place.
        7. Recreate every index that previously lived on the table.
        8. Commit.
    """

    if _artefacts_fk_is_cascade(conn) and _artefacts_has_unique_rel_path(conn):
        return

    logger.info("rebuilding artefacts table to add FK CASCADE + UNIQUE(rel_path)")

    cols_csv = ", ".join(_ARTEFACTS_COLUMNS)

    # Foreign-key enforcement MUST be OFF for the rebuild dance so SQLite
    # doesn't refuse the DROP of the original table while child rows
    # still reference it through the new table's not-yet-renamed FK. We
    # restore the prior state in a finally block.
    fk_was_on_row = conn.execute("PRAGMA foreign_keys").fetchone()
    fk_was_on = bool(fk_was_on_row[0]) if fk_was_on_row else True
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        try:
            # Orphan purge — child rows whose parent run was already deleted
            # (would otherwise survive into the new cascading table and could
            # never be cleaned via runs deletion).
            orphans = conn.execute(
                "DELETE FROM artefacts "
                "WHERE run_id NOT IN (SELECT id FROM runs)"
            )
            orphan_count = orphans.rowcount or 0
            if orphan_count:
                logger.info(
                    "artefacts rebuild: purged %d orphan row(s)",
                    orphan_count,
                )

            # Dedupe — required before UNIQUE(rel_path) can be enforced.
            # Keep the highest id (most recent insert) per rel_path.
            dedup = conn.execute(
                "DELETE FROM artefacts WHERE id NOT IN ("
                "  SELECT MAX(id) FROM artefacts GROUP BY rel_path"
                ")"
            )
            dedup_count = dedup.rowcount or 0
            if dedup_count:
                logger.info(
                    "artefacts rebuild: removed %d duplicate rel_path row(s)",
                    dedup_count,
                )

            conn.execute(
                "CREATE TABLE artefacts_new ("
                "  id INTEGER PRIMARY KEY,"
                "  run_id TEXT NOT NULL,"
                "  tool_id TEXT NOT NULL,"
                "  output_key TEXT NOT NULL,"
                "  rel_path TEXT NOT NULL,"
                "  filename TEXT NOT NULL,"
                "  mime TEXT NOT NULL,"
                "  size_bytes INTEGER NOT NULL,"
                "  sha256 TEXT NOT NULL,"
                "  created_at TIMESTAMP NOT NULL,"
                "  starred INTEGER NOT NULL DEFAULT 0,"
                "  label TEXT,"
                "  tags TEXT,"
                "  thumb_path TEXT,"
                "  deleted_at TIMESTAMP,"
                "  UNIQUE(rel_path),"
                "  FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE"
                ")"
            )
            conn.execute(
                f"INSERT INTO artefacts_new ({cols_csv}) "
                f"SELECT {cols_csv} FROM artefacts"
            )
            conn.execute("DROP TABLE artefacts")
            conn.execute("ALTER TABLE artefacts_new RENAME TO artefacts")

            # Recreate the indexes that lived on the original table.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artefacts_run "
                "ON artefacts(run_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artefacts_tool "
                "ON artefacts(tool_id, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artefacts_starred "
                "ON artefacts(starred) WHERE starred = 1"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artefacts_deleted "
                "ON artefacts(deleted_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artefacts_label "
                "ON artefacts(label)"
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        # Restore previous foreign-key enforcement. SQLite's foreign-key
        # check on schema operations is brittle; if there are residual
        # violations we surface them via PRAGMA foreign_key_check before
        # turning enforcement back on so the next commit isn't poisoned.
        if fk_was_on:
            violations = conn.execute(
                "PRAGMA foreign_key_check(artefacts)"
            ).fetchall()
            if violations:
                logger.warning(
                    "artefacts rebuild: %d FK violation(s) remain "
                    "after rebuild (rows orphaned by external deletes); "
                    "leaving foreign_keys OFF for this connection — "
                    "next reconnect re-enables enforcement.",
                    len(violations),
                )
            else:
                conn.execute("PRAGMA foreign_keys = ON")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sync_get_setting(db_path: Path, key: str) -> str | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def _sync_set_setting(db_path: Path, key: str, value: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


async def get_setting(db_path: Path, key: str) -> str | None:
    return await run_in_threadpool(_sync_get_setting, db_path, key)


async def set_setting(db_path: Path, key: str, value: str) -> None:
    await run_in_threadpool(_sync_set_setting, db_path, key, value)


def _sync_record_run_start(
    db_path: Path, run_id: str, tool_id: str, inputs: dict[str, Any]
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs(id, tool_id, started_at, inputs_json, status) "
            "VALUES(?, ?, ?, ?, 'running')",
            (run_id, tool_id, _now(), json.dumps(inputs)),
        )


async def record_run_start(
    db_path: Path, run_id: str, tool_id: str, inputs: dict[str, Any]
) -> None:
    await run_in_threadpool(_sync_record_run_start, db_path, run_id, tool_id, inputs)


def _sync_record_run_finish(
    db_path: Path, run_id: str, outputs: dict[str, Any]
) -> None:
    payload = json.dumps(outputs)
    # When inline outputs exceed 1 MB, the artefact subsystem is expected to
    # have already spilled large values to disk. As a safety net we mark the
    # row as oversize via ``meta_json`` and null out ``outputs_json`` so the
    # row remains addressable but the run history disables replay-with-outputs.
    meta_json: str | None = None
    if len(payload) > 1_000_000:
        meta_json = json.dumps({
            "outputs_oversize": True,
            "bytes": len(payload),
        })
        payload_to_store: str | None = None
    else:
        payload_to_store = payload
    with _connect(db_path) as conn:
        if meta_json is not None:
            conn.execute(
                "UPDATE runs SET finished_at = ?, outputs_json = ?, "
                "       status = 'ok', meta_json = ? "
                "WHERE id = ?",
                (_now(), payload_to_store, meta_json, run_id),
            )
        else:
            conn.execute(
                "UPDATE runs SET finished_at = ?, outputs_json = ?, "
                "       status = 'ok' WHERE id = ?",
                (_now(), payload_to_store, run_id),
            )


async def record_run_finish(
    db_path: Path, run_id: str, outputs: dict[str, Any]
) -> None:
    await run_in_threadpool(_sync_record_run_finish, db_path, run_id, outputs)


def _sync_record_run_cancelled(db_path: Path, run_id: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = 'cancelled' "
            "WHERE id = ? AND status IN ('running', 'error')",
            (_now(), run_id),
        )


async def record_run_cancelled(db_path: Path, run_id: str) -> None:
    """Mark a still-running run as cancelled. Idempotent if already finished."""

    await run_in_threadpool(_sync_record_run_cancelled, db_path, run_id)


def _sync_prune_old_runs_per_tool(db_path: Path, tool_id: str, keep: int) -> int:
    """Keep the most-recent ``keep`` runs for one tool; delete older rows."""

    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM runs WHERE id IN ("
            "  SELECT id FROM runs WHERE tool_id = ? "
            "  ORDER BY started_at DESC LIMIT -1 OFFSET ?"
            ")",
            (tool_id, keep),
        )
        return cur.rowcount or 0


async def prune_old_runs_per_tool(
    db_path: Path, tool_id: str, keep: int = 100
) -> int:
    """Trim ``runs`` for one tool to the most-recent ``keep`` rows."""

    return await run_in_threadpool(
        _sync_prune_old_runs_per_tool, db_path, tool_id, keep
    )


def _summarise_inputs(inputs_json: str | None) -> str:
    """One-line preview of the first non-empty input value (truncated to 60)."""

    try:
        data = json.loads(inputs_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return ""
    if isinstance(data, dict) and "inputs" in data and isinstance(data["inputs"], dict):
        data = data["inputs"]
    if not isinstance(data, dict):
        return ""
    for key, value in data.items():
        if value is None or value == "" or value == []:
            continue
        text = str(value)
        if len(text) > 60:
            text = text[:60] + "…"
        return f"{key}: {text}"
    return ""


def _sync_recent_runs_all_tools(db_path: Path, limit: int) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, tool_id, started_at, finished_at, status, "
            "       inputs_json, error_text "
            "FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "run_id": row["id"],
            "tool_id": row["tool_id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "summary": _summarise_inputs(row["inputs_json"]),
        }
        for row in rows
    ]


async def recent_runs_all_tools(
    db_path: Path, limit: int = 5
) -> list[dict[str, Any]]:
    """Return the N most-recent runs across all tools, newest first."""

    return await run_in_threadpool(_sync_recent_runs_all_tools, db_path, limit)


def _sync_list_runs_with_inputs(
    db_path: Path, tool_id: str, limit: int
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, tool_id, started_at, finished_at, status, "
            "       inputs_json, error_text "
            "FROM runs WHERE tool_id = ? ORDER BY started_at DESC LIMIT ?",
            (tool_id, limit),
        ).fetchall()
    return [
        {
            "run_id": row["id"],
            "tool_id": row["tool_id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "summary": _summarise_inputs(row["inputs_json"]),
        }
        for row in rows
    ]


async def list_runs_with_inputs(
    db_path: Path, tool_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Run list with one-line inputs preview - used by the history popover."""

    return await run_in_threadpool(
        _sync_list_runs_with_inputs, db_path, tool_id, limit
    )


def _sync_record_run_error(
    db_path: Path, run_id: str, error_text: str, status: str = "error"
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, error_text = ?, status = ? "
            "WHERE id = ?",
            (_now(), error_text, status, run_id),
        )


async def record_run_error(
    db_path: Path, run_id: str, error_text: str, status: str = "error"
) -> None:
    await run_in_threadpool(_sync_record_run_error, db_path, run_id, error_text, status)


def _sync_list_runs(db_path: Path, tool_id: str, limit: int) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, tool_id, started_at, finished_at, status, error_text "
            "FROM runs WHERE tool_id = ? ORDER BY started_at DESC LIMIT ?",
            (tool_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


async def list_runs(db_path: Path, tool_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return await run_in_threadpool(_sync_list_runs, db_path, tool_id, limit)


def _sync_get_run(db_path: Path, run_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


async def get_run(db_path: Path, run_id: str) -> dict[str, Any] | None:
    return await run_in_threadpool(_sync_get_run, db_path, run_id)


_TOOL_STATE_COLUMNS = (
    "tool_id", "last_inputs_json", "favourited", "sort_order",
    "overrides_json", "archived", "pinned", "pinned_warm",
    "discovery_hash", "run_count_total", "disk_bytes", "last_disk_audit",
    "last_run_at", "default_warm_keep_seconds", "pinned_at",
    "archived_at", "colour", "sort_order_in_workspace_json",
)


def _sync_get_tool_state(db_path: Path, tool_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT {', '.join(_TOOL_STATE_COLUMNS)} "
            "FROM tool_state WHERE tool_id = ?",
            (tool_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        raw_overrides = result.get("overrides_json")
        if raw_overrides:
            try:
                result["overrides"] = json.loads(raw_overrides)
            except json.JSONDecodeError:
                result["overrides"] = {}
        else:
            result["overrides"] = {}
        raw_sort = result.get("sort_order_in_workspace_json")
        if raw_sort:
            try:
                result["sort_order_in_workspace"] = json.loads(raw_sort)
            except json.JSONDecodeError:
                result["sort_order_in_workspace"] = {}
        else:
            result["sort_order_in_workspace"] = {}
        return result


async def get_tool_state(db_path: Path, tool_id: str) -> dict[str, Any] | None:
    return await run_in_threadpool(_sync_get_tool_state, db_path, tool_id)


def _sync_set_tool_state(
    db_path: Path,
    tool_id: str,
    last_inputs: dict[str, Any] | None,
    favourited: bool | None,
    sort_order: int | None,
    overrides: dict[str, Any] | None,
) -> None:
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT last_inputs_json, favourited, sort_order, overrides_json "
            "FROM tool_state WHERE tool_id = ?",
            (tool_id,),
        ).fetchone()
        last_inputs_json = (
            json.dumps(last_inputs) if last_inputs is not None
            else (existing["last_inputs_json"] if existing else None)
        )
        fav_value = (
            int(bool(favourited)) if favourited is not None
            else (existing["favourited"] if existing else 0)
        )
        sort_value = (
            sort_order if sort_order is not None
            else (existing["sort_order"] if existing else None)
        )
        overrides_json = (
            json.dumps(overrides) if overrides is not None
            else (existing["overrides_json"] if existing else None)
        )
        conn.execute(
            "INSERT INTO tool_state(tool_id, last_inputs_json, favourited, "
            "  sort_order, overrides_json) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(tool_id) DO UPDATE SET "
            "  last_inputs_json = excluded.last_inputs_json, "
            "  favourited = excluded.favourited, "
            "  sort_order = excluded.sort_order, "
            "  overrides_json = excluded.overrides_json",
            (tool_id, last_inputs_json, fav_value, sort_value, overrides_json),
        )


async def set_tool_state(
    db_path: Path,
    tool_id: str,
    *,
    last_inputs: dict[str, Any] | None = None,
    favourited: bool | None = None,
    sort_order: int | None = None,
    overrides: dict[str, Any] | None = None,
) -> None:
    await run_in_threadpool(
        _sync_set_tool_state,
        db_path, tool_id, last_inputs, favourited, sort_order, overrides,
    )


async def get_tool_overrides(db_path: Path, tool_id: str) -> dict[str, Any]:
    """Return the per-tool overrides dict (empty if none stored)."""

    state = await get_tool_state(db_path, tool_id)
    if state is None:
        return {}
    return dict(state.get("overrides") or {})


async def set_tool_overrides(
    db_path: Path, tool_id: str, overrides: dict[str, Any]
) -> None:
    """Replace the per-tool overrides dict atomically."""

    await set_tool_state(db_path, tool_id, overrides=overrides)


async def set_favourited(db_path: Path, tool_id: str, favourited: bool) -> None:
    await set_tool_state(db_path, tool_id, favourited=favourited)


def _sync_latest_validation_report(db_path: Path, tool_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT tool_id, timestamp, overall, report_json "
            "FROM validation_reports WHERE tool_id = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (tool_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "tool_id": row["tool_id"],
            "timestamp": row["timestamp"],
            "overall": row["overall"],
            "report": json.loads(row["report_json"]),
        }


async def latest_validation_report(db_path: Path, tool_id: str) -> dict[str, Any] | None:
    return await run_in_threadpool(_sync_latest_validation_report, db_path, tool_id)


def _sync_save_validation_report(db_path: Path, report: dict[str, Any]) -> None:
    tool_id = report["tool_id"]
    timestamp = report.get("timestamp") or _now()
    overall = report["overall"]
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO validation_reports"
            "(tool_id, timestamp, overall, report_json) VALUES(?, ?, ?, ?)",
            (tool_id, timestamp, overall, json.dumps(report)),
        )


async def save_validation_report(db_path: Path, report: dict[str, Any]) -> None:
    await run_in_threadpool(_sync_save_validation_report, db_path, report)


def _sync_prune_old_reports(db_path: Path, days: int) -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM validation_reports WHERE timestamp < ?", (cutoff_iso,)
        )
        return cur.rowcount or 0


async def prune_old_reports(db_path: Path, days: int = 30) -> int:
    return await run_in_threadpool(_sync_prune_old_reports, db_path, days)


# ---------------------------------------------------------------------------
# Maintenance helpers (settings page)
# ---------------------------------------------------------------------------


def _sync_delete_runs(db_path: Path, tool_id: str | None) -> int:
    with _connect(db_path) as conn:
        if tool_id:
            cur = conn.execute("DELETE FROM runs WHERE tool_id = ?", (tool_id,))
        else:
            cur = conn.execute("DELETE FROM runs")
        return cur.rowcount or 0


async def delete_runs(db_path: Path, tool_id: str | None = None) -> int:
    """Delete run history for a single tool (or all tools if ``tool_id`` is None).

    Returns the number of rows removed.
    """

    return await run_in_threadpool(_sync_delete_runs, db_path, tool_id)


def _sync_vacuum(db_path: Path) -> int:
    """Run VACUUM + ANALYZE, returning the new on-disk file size in bytes.

    ANALYZE follows VACUUM in the same connection so the query planner's
    ``sqlite_stat1`` table is repopulated against the freshly compacted
    pages. Both statements must run outside any transaction; the
    connection opens with ``isolation_level=None`` (autocommit) so the
    bare statements work.
    """

    with _connect(db_path) as conn:
        conn.execute("VACUUM")
        conn.execute("ANALYZE")
    return db_path.stat().st_size if db_path.exists() else 0


async def vacuum(db_path: Path) -> int:
    return await run_in_threadpool(_sync_vacuum, db_path)


def _sync_analyze(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute("ANALYZE")


async def analyze(db_path: Path) -> None:
    """Refresh SQLite's query-planner stats (``sqlite_stat1``).

    Cheap to run periodically; called from the sweeper so the planner
    keeps up with shifting table sizes between full VACUUM cycles.
    """

    await run_in_threadpool(_sync_analyze, db_path)


def _sync_purge_orphan_artefacts(db_path: Path) -> int:
    """Delete artefact rows whose ``run_id`` no longer exists in ``runs``.

    With the cascading FK (see :func:`_rebuild_artefacts_with_cascade_fk`)
    this should normally be a no-op; we still run it because:
        * legacy rows may predate the cascade migration,
        * direct sqlite3.connect() callers historically opened the DB
          with foreign_keys OFF and could orphan rows,
        * external corruption/manual edits can introduce orphans too.
    Returns the number of rows deleted.
    """

    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM artefacts "
            "WHERE run_id NOT IN (SELECT id FROM runs)"
        )
        return cur.rowcount or 0


async def purge_orphan_artefacts(db_path: Path) -> int:
    """Remove artefact rows whose parent run row was deleted."""

    return await run_in_threadpool(_sync_purge_orphan_artefacts, db_path)


def _sync_db_size(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    total = db_path.stat().st_size
    for suffix in ("-wal", "-shm", "-journal"):
        side = db_path.with_name(db_path.name + suffix)
        if side.exists():
            total += side.stat().st_size
    return total


async def db_size_bytes(db_path: Path) -> int:
    return await run_in_threadpool(_sync_db_size, db_path)


# ---------------------------------------------------------------------------
# Star-aware run pruning
# ---------------------------------------------------------------------------


def _sync_prune_starred_aware(db_path: Path, tool_id: str, keep: int) -> int:
    """Prune ``runs`` for ``tool_id`` keeping the latest ``keep`` *un*-starred,
    *un*-labelled rows. Starred and labelled runs are never auto-pruned.

    Returns the number of rows actually deleted.
    """

    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM runs WHERE id IN ("
            "  SELECT id FROM runs "
            "  WHERE tool_id = ? "
            "    AND COALESCE(starred, 0) = 0 "
            "    AND label IS NULL "
            "  ORDER BY started_at DESC "
            "  LIMIT -1 OFFSET ?"
            ")",
            (tool_id, keep),
        )
        return cur.rowcount or 0


async def prune_starred_aware(
    db_path: Path, tool_id: str, keep: int = 100
) -> int:
    """Like :func:`prune_old_runs_per_tool` but never deletes starred/labelled."""

    return await run_in_threadpool(
        _sync_prune_starred_aware, db_path, tool_id, keep
    )


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------


def _sync_register_artefact(
    db_path: Path,
    *,
    run_id: str,
    tool_id: str,
    output_key: str,
    rel_path: str,
    filename: str,
    mime: str,
    size_bytes: int,
    sha256: str,
    label: str | None = None,
    tags: list[str] | None = None,
    thumb_path: str | None = None,
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO artefacts("
            "  run_id, tool_id, output_key, rel_path, filename, mime, "
            "  size_bytes, sha256, created_at, label, tags, thumb_path"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id, tool_id, output_key, rel_path, filename, mime,
                size_bytes, sha256, _now(), label,
                json.dumps(tags) if tags else None, thumb_path,
            ),
        )
        # Keep ``runs.total_artefact_bytes`` denormalised so the run-history
        # row can show "23 MB across 4 files" without a separate aggregate query.
        conn.execute(
            "UPDATE runs "
            "SET total_artefact_bytes = COALESCE(total_artefact_bytes, 0) + ? "
            "WHERE id = ?",
            (size_bytes, run_id),
        )
        return int(cur.lastrowid or 0)


async def register_artefact(
    db_path: Path,
    *,
    run_id: str,
    tool_id: str,
    output_key: str,
    rel_path: str,
    filename: str,
    mime: str,
    size_bytes: int,
    sha256: str,
    label: str | None = None,
    tags: list[str] | None = None,
    thumb_path: str | None = None,
) -> int:
    # `_pixie_run_outputs` is reserved for the internal run-outputs.json
    # artefact (registered with output_key="_pixie_run_outputs"). Reject any
    # other caller that tries to claim it.
    if tags and "_pixie_run_outputs" in tags and output_key != "_pixie_run_outputs":
        raise ValueError(
            "tag '_pixie_run_outputs' is reserved for Pixie's internal "
            "run-outputs artefact and cannot be set by tools or callers"
        )
    return await run_in_threadpool(
        _sync_register_artefact, db_path,
        run_id=run_id, tool_id=tool_id, output_key=output_key,
        rel_path=rel_path, filename=filename, mime=mime,
        size_bytes=size_bytes, sha256=sha256, label=label,
        tags=tags, thumb_path=thumb_path,
    )


def _row_to_artefact(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    raw_tags = record.get("tags")
    if raw_tags:
        try:
            record["tags"] = json.loads(raw_tags)
        except json.JSONDecodeError:
            record["tags"] = []
    else:
        record["tags"] = []
    return record


def _sync_list_artefacts(
    db_path: Path,
    *,
    tool_id: str | None,
    run_id: str | None,
    mime: str | None,
    starred: bool | None,
    label: str | None,
    tag: str | None,
    include_deleted: bool,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if not include_deleted:
        clauses.append("deleted_at IS NULL")
    if tool_id is not None:
        clauses.append("tool_id = ?")
        params.append(tool_id)
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if mime is not None:
        clauses.append("mime LIKE ?")
        params.append(mime)
    if starred is True:
        clauses.append("starred = 1")
    elif starred is False:
        clauses.append("starred = 0")
    if label is not None:
        clauses.append("label = ?")
        params.append(label)
    if tag is not None:
        # SQLite-native JSON membership scan — index lookup happens on tool_id.
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(tags) WHERE value = ?)"
        )
        params.append(tag)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([limit, offset])
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_id, tool_id, output_key, rel_path, filename, "
            "       mime, size_bytes, sha256, created_at, starred, label, "
            "       tags, thumb_path, deleted_at "
            f"FROM artefacts{where} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    return [_row_to_artefact(row) for row in rows]


async def list_artefacts(
    db_path: Path,
    *,
    tool_id: str | None = None,
    run_id: str | None = None,
    mime: str | None = None,
    starred: bool | None = None,
    label: str | None = None,
    tag: str | None = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return await run_in_threadpool(
        _sync_list_artefacts, db_path,
        tool_id=tool_id, run_id=run_id, mime=mime, starred=starred,
        label=label, tag=tag, include_deleted=include_deleted,
        limit=limit, offset=offset,
    )


def _sync_get_artefact(db_path: Path, artefact_id: int) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, run_id, tool_id, output_key, rel_path, filename, "
            "       mime, size_bytes, sha256, created_at, starred, label, "
            "       tags, thumb_path, deleted_at "
            "FROM artefacts WHERE id = ?",
            (artefact_id,),
        ).fetchone()
        return _row_to_artefact(row) if row else None


async def get_artefact(db_path: Path, artefact_id: int) -> dict[str, Any] | None:
    return await run_in_threadpool(_sync_get_artefact, db_path, artefact_id)


def _sync_star_artefact(db_path: Path, artefact_id: int, on: bool) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE artefacts SET starred = ? WHERE id = ?",
            (1 if on else 0, artefact_id),
        )


async def star_artefact(db_path: Path, artefact_id: int, on: bool) -> None:
    await run_in_threadpool(_sync_star_artefact, db_path, artefact_id, on)


def _sync_label_artefact(
    db_path: Path,
    artefact_id: int,
    label: str | None,
    tags: list[str] | None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE artefacts SET label = ?, tags = ? WHERE id = ?",
            (
                label,
                json.dumps(tags) if tags is not None else None,
                artefact_id,
            ),
        )


async def label_artefact(
    db_path: Path,
    artefact_id: int,
    *,
    label: str | None = None,
    tags: list[str] | None = None,
) -> None:
    """Set the artefact's label and/or tag list. ``None`` clears either field."""

    await run_in_threadpool(
        _sync_label_artefact, db_path, artefact_id, label, tags
    )


def _sync_soft_delete_artefact(db_path: Path, artefact_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE artefacts SET deleted_at = ? WHERE id = ?",
            (_now(), artefact_id),
        )


async def soft_delete_artefact(db_path: Path, artefact_id: int) -> None:
    """Soft-delete an artefact (sweeper hard-deletes after the trash window)."""

    await run_in_threadpool(_sync_soft_delete_artefact, db_path, artefact_id)


def _sync_purge_soft_deleted(db_path: Path, older_than_days: int) -> list[dict[str, Any]]:
    """Return the rows that were deleted so the caller can unlink files."""

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=older_than_days)
    ).isoformat()
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, rel_path, thumb_path FROM artefacts "
            "WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        ).fetchall()
        purged = [dict(row) for row in rows]
        if purged:
            ids = [row["id"] for row in purged]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"DELETE FROM artefacts WHERE id IN ({placeholders})",
                ids,
            )
    return purged


async def purge_soft_deleted(
    db_path: Path, older_than_days: int = 7
) -> list[dict[str, Any]]:
    """Hard-delete artefact rows soft-deleted more than ``N`` days ago.

    Returns the (id, rel_path, thumb_path) tuples so the caller can unlink
    the backing files and any cached thumbnails.
    """

    return await run_in_threadpool(
        _sync_purge_soft_deleted, db_path, older_than_days
    )


def _sync_total_artefact_bytes(db_path: Path, tool_id: str) -> int:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM artefacts "
            "WHERE tool_id = ? AND deleted_at IS NULL",
            (tool_id,),
        ).fetchone()
        return int(row["total"] if row else 0)


async def total_artefact_bytes(db_path: Path, tool_id: str) -> int:
    """Live total of un-soft-deleted artefact bytes for one tool."""

    return await run_in_threadpool(_sync_total_artefact_bytes, db_path, tool_id)


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


def _sync_create_workspace(
    db_path: Path,
    name: str,
    colour: str | None,
    sort_order: int,
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO workspaces(name, colour, sort_order, created_at) "
            "VALUES(?, ?, ?, ?)",
            (name, colour, sort_order, _now()),
        )
        return int(cur.lastrowid or 0)


async def create_workspace(
    db_path: Path,
    name: str,
    *,
    colour: str | None = None,
    sort_order: int = 0,
) -> int:
    return await run_in_threadpool(
        _sync_create_workspace, db_path, name, colour, sort_order
    )


def _sync_list_workspaces(db_path: Path) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, colour, sort_order, collapsed, created_at "
            "FROM workspaces ORDER BY sort_order ASC, name ASC"
        ).fetchall()
        return [dict(row) for row in rows]


async def list_workspaces(db_path: Path) -> list[dict[str, Any]]:
    return await run_in_threadpool(_sync_list_workspaces, db_path)


def _sync_rename_workspace(
    db_path: Path,
    workspace_id: int,
    *,
    name: str | None,
    colour: str | None,
    sort_order: int | None,
    collapsed: bool | None,
) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if colour is not None:
        sets.append("colour = ?")
        params.append(colour)
    if sort_order is not None:
        sets.append("sort_order = ?")
        params.append(sort_order)
    if collapsed is not None:
        sets.append("collapsed = ?")
        params.append(1 if collapsed else 0)
    if not sets:
        return
    params.append(workspace_id)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE workspaces SET {', '.join(sets)} WHERE id = ?",
            params,
        )


async def rename_workspace(
    db_path: Path,
    workspace_id: int,
    *,
    name: str | None = None,
    colour: str | None = None,
    sort_order: int | None = None,
    collapsed: bool | None = None,
) -> None:
    """Update mutable workspace fields. Pass only the fields you want changed."""

    await run_in_threadpool(
        _sync_rename_workspace, db_path, workspace_id,
        name=name, colour=colour, sort_order=sort_order, collapsed=collapsed,
    )


def _sync_delete_workspace(db_path: Path, workspace_id: int) -> None:
    with _connect(db_path) as conn:
        # ON DELETE CASCADE on tool_workspaces removes membership rows.
        conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))


async def delete_workspace(db_path: Path, workspace_id: int) -> None:
    await run_in_threadpool(_sync_delete_workspace, db_path, workspace_id)


def _sync_add_tool_to_workspace(
    db_path: Path, tool_id: str, workspace_id: int
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO tool_workspaces(tool_id, workspace_id, added_at) "
            "VALUES(?, ?, ?) "
            "ON CONFLICT(tool_id, workspace_id) DO NOTHING",
            (tool_id, workspace_id, _now()),
        )


async def add_tool_to_workspace(
    db_path: Path, tool_id: str, workspace_id: int
) -> None:
    await run_in_threadpool(
        _sync_add_tool_to_workspace, db_path, tool_id, workspace_id
    )


def _sync_remove_tool_from_workspace(
    db_path: Path, tool_id: str, workspace_id: int
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM tool_workspaces "
            "WHERE tool_id = ? AND workspace_id = ?",
            (tool_id, workspace_id),
        )


async def remove_tool_from_workspace(
    db_path: Path, tool_id: str, workspace_id: int
) -> None:
    await run_in_threadpool(
        _sync_remove_tool_from_workspace, db_path, tool_id, workspace_id
    )


def _sync_list_tools_in_workspace(
    db_path: Path, workspace_id: int
) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tool_id FROM tool_workspaces "
            "WHERE workspace_id = ? ORDER BY added_at ASC",
            (workspace_id,),
        ).fetchall()
        return [row["tool_id"] for row in rows]


async def list_tools_in_workspace(
    db_path: Path, workspace_id: int
) -> list[str]:
    return await run_in_threadpool(
        _sync_list_tools_in_workspace, db_path, workspace_id
    )


def _sync_list_workspaces_for_tool(
    db_path: Path, tool_id: str
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT w.id, w.name, w.colour, w.sort_order, w.collapsed "
            "FROM workspaces w "
            "JOIN tool_workspaces tw ON tw.workspace_id = w.id "
            "WHERE tw.tool_id = ? ORDER BY w.sort_order ASC, w.name ASC",
            (tool_id,),
        ).fetchall()
        return [dict(row) for row in rows]


async def list_workspaces_for_tool(
    db_path: Path, tool_id: str
) -> list[dict[str, Any]]:
    return await run_in_threadpool(
        _sync_list_workspaces_for_tool, db_path, tool_id
    )


# ---------------------------------------------------------------------------
# Tool tags
# ---------------------------------------------------------------------------


def _sync_add_tag(db_path: Path, tool_id: str, tag: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO tool_tags(tool_id, tag) VALUES(?, ?) "
            "ON CONFLICT(tool_id, tag) DO NOTHING",
            (tool_id, tag),
        )


async def add_tag(db_path: Path, tool_id: str, tag: str) -> None:
    await run_in_threadpool(_sync_add_tag, db_path, tool_id, tag)


def _sync_remove_tag(db_path: Path, tool_id: str, tag: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM tool_tags WHERE tool_id = ? AND tag = ?",
            (tool_id, tag),
        )


async def remove_tag(db_path: Path, tool_id: str, tag: str) -> None:
    await run_in_threadpool(_sync_remove_tag, db_path, tool_id, tag)


def _sync_list_tags(db_path: Path, tool_id: str) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tag FROM tool_tags WHERE tool_id = ? ORDER BY tag ASC",
            (tool_id,),
        ).fetchall()
        return [row["tag"] for row in rows]


async def list_tags(db_path: Path, tool_id: str) -> list[str]:
    return await run_in_threadpool(_sync_list_tags, db_path, tool_id)


def _sync_all_tags(db_path: Path) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT tag FROM tool_tags ORDER BY tag ASC"
        ).fetchall()
        return [row["tag"] for row in rows]


async def all_tags(db_path: Path) -> list[str]:
    return await run_in_threadpool(_sync_all_tags, db_path)


def _sync_find_tools_by_tag(db_path: Path, tag: str) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tool_id FROM tool_tags WHERE tag = ? ORDER BY tool_id",
            (tag,),
        ).fetchall()
        return [row["tool_id"] for row in rows]


async def find_tools_by_tag(db_path: Path, tag: str) -> list[str]:
    return await run_in_threadpool(_sync_find_tools_by_tag, db_path, tag)


# ---------------------------------------------------------------------------
# Validate jobs (validate-all progress tracking)
# ---------------------------------------------------------------------------


def _sync_start_validate_job(db_path: Path, job_id: str, total: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO validate_jobs("
            "  id, started_at, status, total, completed, passed, warned, failed"
            ") VALUES(?, ?, 'running', ?, 0, 0, 0, 0)",
            (job_id, _now(), total),
        )


async def start_validate_job(
    db_path: Path, job_id: str, total: int
) -> None:
    await run_in_threadpool(_sync_start_validate_job, db_path, job_id, total)


def _sync_update_validate_job(
    db_path: Path,
    job_id: str,
    updates: dict[str, Any],
) -> None:
    if not updates:
        return
    allowed = {
        "status", "completed", "passed", "warned", "failed",
        "finished_at", "details_json", "total",
    }
    sets: list[str] = []
    params: list[Any] = []
    for key, value in updates.items():
        if key not in allowed:
            continue
        if key == "details_json" and not isinstance(value, str):
            value = json.dumps(value)
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return
    params.append(job_id)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE validate_jobs SET {', '.join(sets)} WHERE id = ?",
            params,
        )


async def update_validate_job(db_path: Path, job_id: str, **updates: Any) -> None:
    """Patch any subset of mutable validate-job columns.

    Recognised keys: ``status``, ``completed``, ``passed``, ``warned``,
    ``failed``, ``finished_at``, ``details_json``, ``total``.
    """

    await run_in_threadpool(_sync_update_validate_job, db_path, job_id, updates)


def _sync_get_validate_job(db_path: Path, job_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, started_at, finished_at, status, total, completed, "
            "       passed, warned, failed, details_json "
            "FROM validate_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        record = dict(row)
        raw = record.get("details_json")
        if raw:
            try:
                record["details"] = json.loads(raw)
            except json.JSONDecodeError:
                record["details"] = None
        return record


async def get_validate_job(db_path: Path, job_id: str) -> dict[str, Any] | None:
    return await run_in_threadpool(_sync_get_validate_job, db_path, job_id)


# ---------------------------------------------------------------------------
# Tool-state extensions (archive / pin / disk audit / colour)
# ---------------------------------------------------------------------------


def _sync_ensure_tool_state_row(conn: sqlite3.Connection, tool_id: str) -> None:
    conn.execute(
        "INSERT INTO tool_state(tool_id, favourited) VALUES(?, 0) "
        "ON CONFLICT(tool_id) DO NOTHING",
        (tool_id,),
    )


def _sync_set_archived(db_path: Path, tool_id: str, archived: bool) -> None:
    with _connect(db_path) as conn:
        _sync_ensure_tool_state_row(conn, tool_id)
        conn.execute(
            "UPDATE tool_state SET archived = ?, archived_at = ? "
            "WHERE tool_id = ?",
            (1 if archived else 0, _now() if archived else None, tool_id),
        )


async def set_archived(db_path: Path, tool_id: str, archived: bool) -> None:
    await run_in_threadpool(_sync_set_archived, db_path, tool_id, archived)


# ---------------------------------------------------------------------------
# Archive log (4.1) — distinguish intentional archive from orphaned flags
# ---------------------------------------------------------------------------


def _sync_log_archive(db_path: Path, tool_id: str, source: str) -> None:
    """Record an intentional archive event so sweep can distinguish
    legitimate archived tools from orphaned ``archived=1`` flags.
    """

    if source not in ("cli", "api", "test"):
        source = "api"
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO archive_log(tool_id, source) VALUES(?, ?)",
            (tool_id, source),
        )


async def log_archive(db_path: Path, tool_id: str, source: str) -> None:
    await run_in_threadpool(_sync_log_archive, db_path, tool_id, source)


def _sync_unlog_archive(db_path: Path, tool_id: str) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM archive_log WHERE tool_id = ?",
            (tool_id,),
        )
        return cur.rowcount or 0


async def unlog_archive(db_path: Path, tool_id: str) -> int:
    return await run_in_threadpool(_sync_unlog_archive, db_path, tool_id)


def _sync_has_archive_log(db_path: Path, tool_id: str) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM archive_log WHERE tool_id = ? LIMIT 1",
            (tool_id,),
        ).fetchone()
        return row is not None


async def has_archive_log(db_path: Path, tool_id: str) -> bool:
    return await run_in_threadpool(_sync_has_archive_log, db_path, tool_id)


def _sync_list_archived_tools(db_path: Path) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tool_id FROM tool_state WHERE archived = 1"
        ).fetchall()
        return [row["tool_id"] for row in rows]


async def list_archived_tools(db_path: Path) -> list[str]:
    return await run_in_threadpool(_sync_list_archived_tools, db_path)


def _sync_set_pinned(db_path: Path, tool_id: str, pinned: bool) -> None:
    with _connect(db_path) as conn:
        _sync_ensure_tool_state_row(conn, tool_id)
        conn.execute(
            "UPDATE tool_state SET pinned = ?, pinned_at = ? WHERE tool_id = ?",
            (1 if pinned else 0, _now() if pinned else None, tool_id),
        )


async def set_pinned(db_path: Path, tool_id: str, pinned: bool) -> None:
    await run_in_threadpool(_sync_set_pinned, db_path, tool_id, pinned)


def _sync_set_pinned_warm(db_path: Path, tool_id: str, on: bool) -> None:
    with _connect(db_path) as conn:
        _sync_ensure_tool_state_row(conn, tool_id)
        conn.execute(
            "UPDATE tool_state SET pinned_warm = ? WHERE tool_id = ?",
            (1 if on else 0, tool_id),
        )


async def set_pinned_warm(db_path: Path, tool_id: str, on: bool) -> None:
    await run_in_threadpool(_sync_set_pinned_warm, db_path, tool_id, on)


def _sync_set_discovery_hash(
    db_path: Path, tool_id: str, discovery_hash: str
) -> None:
    with _connect(db_path) as conn:
        _sync_ensure_tool_state_row(conn, tool_id)
        conn.execute(
            "UPDATE tool_state SET discovery_hash = ? WHERE tool_id = ?",
            (discovery_hash, tool_id),
        )


async def set_discovery_hash(
    db_path: Path, tool_id: str, discovery_hash: str
) -> None:
    """Persist the per-tool discovery fingerprint used for cache decisions."""

    await run_in_threadpool(
        _sync_set_discovery_hash, db_path, tool_id, discovery_hash
    )


def _sync_update_disk_bytes(
    db_path: Path, tool_id: str, disk_bytes: int
) -> None:
    with _connect(db_path) as conn:
        _sync_ensure_tool_state_row(conn, tool_id)
        conn.execute(
            "UPDATE tool_state "
            "SET disk_bytes = ?, last_disk_audit = ? WHERE tool_id = ?",
            (disk_bytes, _now(), tool_id),
        )


async def update_disk_bytes(
    db_path: Path, tool_id: str, disk_bytes: int
) -> None:
    """Record the latest computed venv + artefacts byte total for a tool."""

    await run_in_threadpool(
        _sync_update_disk_bytes, db_path, tool_id, disk_bytes
    )


def _sync_set_default_warm_keep(
    db_path: Path, tool_id: str, seconds: int | None
) -> None:
    with _connect(db_path) as conn:
        _sync_ensure_tool_state_row(conn, tool_id)
        conn.execute(
            "UPDATE tool_state SET default_warm_keep_seconds = ? "
            "WHERE tool_id = ?",
            (seconds, tool_id),
        )


async def set_default_warm_keep(
    db_path: Path, tool_id: str, seconds: int | None
) -> None:
    await run_in_threadpool(
        _sync_set_default_warm_keep, db_path, tool_id, seconds
    )


def _sync_set_colour(db_path: Path, tool_id: str, colour: str | None) -> None:
    with _connect(db_path) as conn:
        _sync_ensure_tool_state_row(conn, tool_id)
        conn.execute(
            "UPDATE tool_state SET colour = ? WHERE tool_id = ?",
            (colour, tool_id),
        )


async def set_colour(db_path: Path, tool_id: str, colour: str | None) -> None:
    """Set the optional per-tool sidebar tint (or clear with ``None``)."""

    await run_in_threadpool(_sync_set_colour, db_path, tool_id, colour)


def _sync_bump_run_counters(db_path: Path, tool_id: str) -> None:
    """Increment ``run_count_total`` and refresh ``last_run_at`` for one tool."""

    with _connect(db_path) as conn:
        _sync_ensure_tool_state_row(conn, tool_id)
        conn.execute(
            "UPDATE tool_state "
            "SET run_count_total = COALESCE(run_count_total, 0) + 1, "
            "    last_run_at = ? "
            "WHERE tool_id = ?",
            (_now(), tool_id),
        )


async def bump_run_counters(db_path: Path, tool_id: str) -> None:
    """Inline counter bump — called by the proxy at run-start."""

    await run_in_threadpool(_sync_bump_run_counters, db_path, tool_id)
