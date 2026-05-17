---
title: Configuration
description: Every Pixie setting, its default, and how to override it.
sidebar:
  order: 4
---

Pixie reads configuration from environment variables prefixed `PIXIE_`
and from an optional `.env` file in the repo root. The class lives at
`pixie/config.py` (`Settings(BaseSettings)`).

## Settings reference

| Setting                              | Default                          | Env var                                | Notes                                                                                       |
| ------------------------------------ | -------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------- |
| `port`                               | `7860`                           | `PIXIE_PORT`                           | TCP port on loopback.                                                                       |
| `host`                               | `127.0.0.1`                      | `PIXIE_HOST`                           | **Must** be in `127.0.0.0/8` or `::1`. Public binding refused at startup.                  |
| `tools_dir`                          | `<repo_root>/tools`              | `PIXIE_TOOLS_DIR`                      | Where to look for tool folders.                                                             |
| `db_path`                            | `<repo_root>/pixie.db`           | `PIXIE_DB_PATH`                        | SQLite file path.                                                                           |
| `artefacts_root`                     | `<repo_root>/artefacts`          | `PIXIE_ARTEFACTS_ROOT`                 | Where spilled artefacts live.                                                               |
| `warm_keep_seconds`                  | `300`                            | `PIXIE_WARM_KEEP_SECONDS`              | Default per-tool TTL after last use.                                                        |
| `warm_keep_max`                      | `5`                              | `PIXIE_WARM_MAX`                       | Global LRU cap on warm tool subprocesses.                                                   |
| `developer_mode`                     | `false`                          | `PIXIE_DEVELOPER_MODE`                 | Enables dev-only routes and verbose debug.                                                  |
| `theme`                              | `"light"`                        | `PIXIE_THEME`                          | `"light"` or `"dark"`.                                                                      |
| `accent`                             | `"indigo"`                       | `PIXIE_ACCENT`                         | `indigo`, `slate`, `forest`, `ember`.                                                       |
| `density`                            | `"comfortable"`                  | `PIXIE_DENSITY`                        | `compact`, `comfortable`, `airy`.                                                           |
| `max_artefact_bytes_per_run`         | `10 * 1024**3` (10 GiB)          | `PIXIE_MAX_ARTEFACT_BYTES_PER_RUN`     | Quota watchdog SIGKILLs a tool exceeding this.                                              |
| `max_artefacts_per_run`              | `10_000`                         | `PIXIE_MAX_ARTEFACTS_PER_RUN`          | Per-run artefact count cap.                                                                 |
| `artefacts_total_disk_cap_bytes`     | `None` (unlimited)               | `PIXIE_ARTEFACTS_TOTAL_DISK_CAP_BYTES` | Global cap across all tools.                                                                |
| `dedup_artefacts`                    | `false`                          | `PIXIE_DEDUP_ARTEFACTS`                | Content-address dedup via SHA-256.                                                          |
| `thumb_max_edge_px`                  | `256`                            | `PIXIE_THUMB_MAX_EDGE_PX`              | Thumbnail max dimension.                                                                    |
| `thumb_workers`                      | `2`                              | `PIXIE_THUMB_WORKERS`                  | Thumbnail-generation worker threads.                                                        |
| `sweeper_interval_seconds`           | `21_600` (6h)                    | `PIXIE_SWEEPER_INTERVAL_SECONDS`       | Retention sweeper cadence.                                                                  |
| `soft_delete_retention_days`         | `7`                              | `PIXIE_SOFT_DELETE_RETENTION_DAYS`     | Days before soft-deleted artefacts are hard-removed.                                        |
| `inline_output_max_bytes`            | `65_536` (64 KiB)                | `PIXIE_INLINE_OUTPUT_MAX_BYTES`        | Above this, outputs spill to `artefacts/` instead of `runs.outputs_json`.                   |
| `library_page_size`                  | `50`                             | `PIXIE_LIBRARY_PAGE_SIZE`              | Library / gallery pagination.                                                               |

## Where to put values

In precedence order, lowest wins (highest overrides):

1. Defaults in `pixie/config.py`.
2. `.env` file in the repo root.
3. Environment variables (`PIXIE_*`).

The repo's default `.env` is gitignored. Create one if you want
per-machine overrides:

```bash
# .env at repo root
PIXIE_PORT=8000
PIXIE_THEME=dark
PIXIE_WARM_KEEP_SECONDS=600
PIXIE_DEVELOPER_MODE=true
```

## Per-tool overrides

Some defaults are overridden per-tool in `tool.json`:

- `warm_keep_seconds` — override the global default for a heavy tool
  you want to stay warm longer (e.g. Whisper).
- `max_memory_mb`, `max_runtime_seconds` — set resource limits.
- `retain_runs` — how many runs to keep before LRU eviction.

These take precedence over the global setting for that one tool.

## What you cannot override

- The `host` cannot bind to anything outside `127.0.0.0/8` or `::1`.
  This is enforced at config validation time and again at app startup.
- `repo_root`, `static_dir`, `templates_dir` — auto-detected from the
  package layout; not overrideable.

## See also

- [CLI](/Pixie/reference/cli/) — the `--port`, `--tools-dir`, and other
  flags override env vars for one invocation.
- [Database schema](/Pixie/reference/database/) — the `settings` table
  is separate from the env-var pipeline and is used for UI-driven
  preferences that persist across restarts.
