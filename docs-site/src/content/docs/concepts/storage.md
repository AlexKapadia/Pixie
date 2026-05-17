---
title: Storage & runs
description: SQLite tables, run history, artefact spill, and the retention sweeper.
sidebar:
  order: 5
---

Pixie keeps a small amount of state — UI prefs, run history, validation
reports, artefact metadata. All of it lives in a single SQLite file
(`pixie.db`) at the repo root, plus an `artefacts/` directory for large
output files.

## The database

WAL mode, 5-second busy timeout, foreign keys on. Schema is idempotent —
re-running `init_db` against an existing DB is a no-op. Column migrations
are applied via `ALTER TABLE` with "duplicate column" errors swallowed.

Nine tables in total. The shapes that matter:

### `runs` — every tool invocation

```sql
CREATE TABLE runs (
    id              TEXT PRIMARY KEY,           -- UUID
    tool_id         TEXT NOT NULL,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    inputs_json     TEXT NOT NULL,
    outputs_json    TEXT,                       -- NULL if >1MB (spilled)
    error_text      TEXT,
    status          TEXT NOT NULL               -- running | ok | error | cancelled
);

-- Migrated columns
ALTER TABLE runs ADD COLUMN starred              INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN label                TEXT;
ALTER TABLE runs ADD COLUMN total_artefact_bytes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN meta_json            TEXT;
```

Every `POST /tool/<id>/run` creates a row. The `inputs_json` is the
exact JSON sent to the tool. The `outputs_json` is the response if it fits
inline; if it exceeds `inline_output_max_bytes` (default 64 KiB), it is
nulled out and `meta_json` records `{"outputs_oversize": true}`. The actual
output values land in `artefacts` instead.

The run history dropdown on each tool page reads from this table. Clicking
a past run rebuilds both the input form and the output panel from the
stored JSON.

### `validation_reports` — the gatekeeper cache

```sql
CREATE TABLE validation_reports (
    tool_id     TEXT NOT NULL,
    timestamp   TIMESTAMP NOT NULL,
    overall     TEXT NOT NULL,                  -- pass | warn | fail | skip
    report_json TEXT NOT NULL,
    PRIMARY KEY (tool_id, timestamp)
);
```

The latest report per tool is what the sidebar dot reads. Older reports
are kept for 30 days for debugging history then pruned.

### `tool_state` — per-tool UI state

```sql
CREATE TABLE tool_state (
    tool_id           TEXT PRIMARY KEY,
    last_inputs_json  TEXT,                     -- pre-fill the form
    favourited        INTEGER NOT NULL DEFAULT 0,
    sort_order        INTEGER
);

-- Migrated columns: overrides_json, archived, pinned, pinned_warm,
-- discovery_hash, run_count_total, disk_bytes, last_disk_audit,
-- last_run_at, default_warm_keep_seconds, pinned_at, archived_at,
-- colour, sort_order_in_workspace_json
```

`last_inputs_json` is updated on every successful run so re-opening a tool
shows the form pre-filled with what you typed last time.

### `artefacts` — large output spill

```sql
CREATE TABLE artefacts (
    id           INTEGER PRIMARY KEY,
    run_id       TEXT NOT NULL,
    tool_id      TEXT NOT NULL,
    output_key   TEXT NOT NULL,
    rel_path     TEXT NOT NULL,                 -- under artefacts/
    filename     TEXT NOT NULL,
    mime         TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    sha256       TEXT NOT NULL,
    created_at   TIMESTAMP NOT NULL,
    starred      INTEGER NOT NULL DEFAULT 0,
    label        TEXT,
    tags         TEXT,                          -- comma-separated
    thumb_path   TEXT,
    deleted_at   TIMESTAMP,                     -- soft delete
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
```

Any output too big for inline storage is written to `artefacts/<tool_id>/<run_id>/<filename>`
and indexed here. SHA-256 enables optional content-address deduplication
(set `PIXIE_DEDUP_ARTEFACTS=1`).

### `workspaces`, `tool_workspaces`, `tool_tags`

Sidebar grouping (workspaces) and free-form tagging (tags) for filtering.
Deleting a workspace cascades to remove its tool assignments; the tools
themselves are untouched.

### `validate_jobs`

Progress rows for `pixie validate-all` and similar batch operations.
Useful when validating dozens of tools at once.

### `settings`

A flat key-value store for UI preferences (theme, density, accent) and
process-wide state.

## Artefact handling

When a tool returns a large file output (`file`, `image`, `audio`, `video`,
or any output > 64 KiB):

1. The proxy writes the data into `artefacts/<tool_id>/<run_id>/<key>.<ext>`.
2. The MIME type is inferred from the filename and verified against the
   declared output type.
3. The file is `sha256`-hashed; if dedup is on and the hash already exists,
   only the metadata row is created (no second copy on disk).
4. The artefact row is inserted.
5. The output value passed to the renderer is rewritten to point at the
   artefact endpoint, not embedded base64.

A pre-run quota watchdog monitors `total_artefact_bytes` against
`max_artefact_bytes_per_run` (default 10 GiB). If a tool tries to write more
than this, the watchdog SIGKILLs it.

## The retention sweeper

Two background asyncio tasks run in the Pixie process:

- **Runs prune** every 6 hours. For each tool, retain the most recent
  `retain_runs` (default 100) — but **never** delete starred or labelled
  runs.
- **Soft-delete purge** every `sweeper_interval_seconds` (default 6 hours).
  Artefacts with `deleted_at < now - soft_delete_retention_days` (default
  7) are hard-removed from disk.

You can run either manually:

```bash
uv run pixie sweep --dry-run
uv run pixie sweep --apply --older-than 30d
uv run pixie sweep --apply --tool whisper-transcription --older-than 7d
```

`--dry-run` (default) reports what would be deleted. `--apply` commits.

The [`clear-old-outputs`](/Pixie/skills/outputs/) skill is the agent-friendly
wrapper.

## Where this stuff lives on disk

```text
pixie/                          (repo root)
├── pixie.db                    SQLite, WAL mode
├── pixie.db-wal                WAL companion
├── pixie.db-shm                shared-memory companion
└── artefacts/
    └── <tool_id>/
        └── <run_id>/
            ├── <output_key_1>.png
            ├── <output_key_2>.csv
            └── ...
```

All three SQLite files are listed in `.gitignore`. So is `artefacts/`.

## Inspecting the DB

It's just SQLite. Open it with anything:

```bash
sqlite3 pixie.db ".schema runs"
sqlite3 pixie.db "SELECT tool_id, COUNT(*) AS n FROM runs GROUP BY tool_id ORDER BY n DESC;"
sqlite3 pixie.db "SELECT * FROM validation_reports WHERE overall = 'fail';"
```

Or use the [`audit-disk-usage`](/Pixie/skills/diagnostics/) skill for a
formatted summary.
