---
title: Database schema
description: Every table in pixie.db with columns, indexes, and what they're used for.
sidebar:
  order: 3
---

Pixie's state lives in a single SQLite file at the repo root (default
`pixie.db`). The database opens with:

- `PRAGMA journal_mode = WAL`
- `PRAGMA synchronous = NORMAL`
- `PRAGMA foreign_keys = ON`
- `PRAGMA busy_timeout = 5000`

Schema is idempotent — `init_db()` is safe to call against an existing
database. Column migrations are applied via `ALTER TABLE` with
"duplicate column" errors swallowed.

## Tables

### `settings`

```sql
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

UI preferences and miscellaneous app state. Set via `set_setting(key,
value)`, read via `get_setting(key)`.

### `runs`

```sql
CREATE TABLE runs (
    id                    TEXT PRIMARY KEY,            -- UUID
    tool_id               TEXT NOT NULL,
    started_at            TIMESTAMP NOT NULL,
    finished_at           TIMESTAMP,
    inputs_json           TEXT NOT NULL,
    outputs_json          TEXT,                        -- NULL if >1MB, spilled
    error_text            TEXT,
    status                TEXT NOT NULL,               -- running | ok | error | cancelled
    starred               INTEGER NOT NULL DEFAULT 0,
    label                 TEXT,
    total_artefact_bytes  INTEGER NOT NULL DEFAULT 0,
    meta_json             TEXT
);
CREATE INDEX idx_runs_tool    ON runs(tool_id, started_at DESC);
CREATE INDEX idx_runs_started ON runs(started_at DESC);
```

Every `POST /tool/<id>/run` creates a row. `outputs_json` is the
response JSON inline if it fits under `inline_output_max_bytes` (default
64 KiB); otherwise it's `NULL` and `meta_json` records
`{"outputs_oversize": true}`.

### `tool_state`

```sql
CREATE TABLE tool_state (
    tool_id                       TEXT PRIMARY KEY,
    last_inputs_json              TEXT,
    favourited                    INTEGER NOT NULL DEFAULT 0,
    sort_order                    INTEGER,
    overrides_json                TEXT,
    archived                      INTEGER NOT NULL DEFAULT 0,
    pinned                        INTEGER NOT NULL DEFAULT 0,
    pinned_warm                   INTEGER NOT NULL DEFAULT 0,
    discovery_hash                TEXT,
    run_count_total               INTEGER NOT NULL DEFAULT 0,
    disk_bytes                    INTEGER,
    last_disk_audit               TIMESTAMP,
    last_run_at                   TIMESTAMP,
    default_warm_keep_seconds     INTEGER,
    pinned_at                     TIMESTAMP,
    archived_at                   TIMESTAMP,
    colour                        TEXT,
    sort_order_in_workspace_json  TEXT
);
CREATE INDEX idx_tool_state_archived ON tool_state(archived);
CREATE INDEX idx_tool_state_pinned   ON tool_state(pinned);
```

Per-tool UI state: form pre-fill, favourite flag, sort order, archived/
pinned toggles, run counters, disk usage cache.

### `validation_reports`

```sql
CREATE TABLE validation_reports (
    tool_id     TEXT NOT NULL,
    timestamp   TIMESTAMP NOT NULL,
    overall     TEXT NOT NULL,          -- pass | fail | warn | skip
    report_json TEXT NOT NULL,
    PRIMARY KEY (tool_id, timestamp)
);
CREATE INDEX idx_validation_latest ON validation_reports(tool_id, timestamp DESC);
```

The latest row per tool is what the sidebar dot reads. Older rows are
kept for 30 days for debugging history then pruned.

### `artefacts`

```sql
CREATE TABLE artefacts (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT NOT NULL,
    tool_id     TEXT NOT NULL,
    output_key  TEXT NOT NULL,
    rel_path    TEXT NOT NULL,           -- relative to artefacts_root
    filename    TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    starred     INTEGER NOT NULL DEFAULT 0,
    label       TEXT,
    tags        TEXT,                    -- comma-separated
    thumb_path  TEXT,
    deleted_at  TIMESTAMP,               -- soft delete
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX idx_artefacts_run     ON artefacts(run_id);
CREATE INDEX idx_artefacts_tool    ON artefacts(tool_id, created_at DESC);
CREATE INDEX idx_artefacts_starred ON artefacts(starred) WHERE starred = 1;
CREATE INDEX idx_artefacts_deleted ON artefacts(deleted_at);
```

Each spilled output gets a row. Files live at `artefacts/<tool_id>/<run_id>/<filename>`.
Soft-delete with `deleted_at`; hard-purged by the sweeper after
`soft_delete_retention_days` (default 7).

### `workspaces`

```sql
CREATE TABLE workspaces (
    id          INTEGER PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    colour      TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    collapsed   INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL
);
```

Named collapsible groups in the sidebar.

### `tool_workspaces`

```sql
CREATE TABLE tool_workspaces (
    tool_id      TEXT NOT NULL,
    workspace_id INTEGER NOT NULL,
    added_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (tool_id, workspace_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
```

Many-to-many join between tools and workspaces. Deleting a workspace
cascades; the tools themselves are untouched.

### `tool_tags`

```sql
CREATE TABLE tool_tags (
    tool_id TEXT NOT NULL,
    tag     TEXT NOT NULL,
    PRIMARY KEY (tool_id, tag)
);
CREATE INDEX idx_tool_tags_tag ON tool_tags(tag);
```

Kebab-case tags for filtering. The reverse index supports "find all
tools tagged X".

### `validate_jobs`

```sql
CREATE TABLE validate_jobs (
    id            TEXT PRIMARY KEY,         -- UUID
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP,
    status        TEXT NOT NULL,            -- running | ok | error
    total         INTEGER NOT NULL,
    completed     INTEGER NOT NULL DEFAULT 0,
    passed        INTEGER NOT NULL DEFAULT 0,
    warned        INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    details_json  TEXT
);
```

Tracks progress of batch validation runs (`revalidate-all` and the
nightly sweep).

## What's NOT in the database

- **Secrets.** They live in each tool's own `tools/<id>/.env`. Pixie
  never copies them to the DB.
- **Tool source code.** That's on the filesystem in `tools/<id>/`.
- **Artefact bytes.** Stored on disk under `artefacts/`. Only metadata
  (path, mime, sha256, etc.) is in the DB.
- **User accounts.** There aren't any.
