---
title: Glossary
description: Pixie-specific terms in one place.
sidebar:
  order: 3
---

## Artefact

A file produced by a tool run, large enough to spill to disk
(`>inline_output_max_bytes`, default 64 KiB). Lives at
`artefacts/<tool_id>/<run_id>/<filename>` with metadata in the
`artefacts` table.

## Cold start

The time between spawning a tool subprocess and `/healthz` returning
200. Typically 150–500 ms for tools without model loading; can be
several seconds for tools that load Whisper / ViT / BERTopic.

## Discovery

The startup scan of `tools/` that parses each `tool.json` and populates
`app.state.discovered_tools`. Re-runnable via the
[`tools-changed`](/Pixie/reference/http-api/) htmx fragment.

## Fixture

A `reference/fixture_*.json` file containing known `inputs` and
`expected_outputs` for opt-in check 12. Used to verify correctness, not
just the contract.

## Layout

Either (a) the top-level `tool.json` field choosing `form` / `chat` /
`split` for the whole page, or (b) the output-level `layout` field
choosing `panel` / `tab` / `inline` for stacking behaviour.

## Launcher

`pixie/launcher.py`. Owns every running tool subprocess. Picks ports,
spawns, polls `/healthz`, tracks warm state, sends SIGTERM/SIGKILL.

## Partial

A Jinja template under `pixie/templates/partials/`. The renderer
dispatches each input or output type to its own partial — `inputs/text.html`,
`outputs/chart_line.html`, etc.

## Pinned

A tool with `tool_state.pinned = 1` (or `pinned_warm = 1`) is exempt
from LRU warm-keep eviction. Still respects its own TTL.

## Proxy

`pixie/proxy.py`. Forwards `POST /tool/<id>/run` and SSE streams to the
tool subprocess via `httpx.AsyncClient`. Manages the per-run artefacts
directory and quota watchdog.

## Renderer

`pixie/renderer/inputs.py` and `outputs.py`. Walks the schema and
dispatches to per-type partials. The schema-driven UI.

## Run

A single tool invocation. Has a UUID `run_id`, an `inputs_json`, an
`outputs_json` (or NULL if spilled), a `status` (`running` / `ok` /
`error` / `cancelled`), and zero or more artefacts.

## Skill

A Claude Code procedure under `.claude/skills/<name>/SKILL.md`. Loads
when you open the repo in Claude Code. The only sanctioned way to
add/modify tools.

## Soft delete

`artefacts.deleted_at` set to a timestamp but the file still on disk.
Hard-purged by the sweeper after `soft_delete_retention_days` (default
7).

## Spawn log

The captured stderr of a tool subprocess during validation, included
in the `ValidationReport` as `spawn_log`. Helpful for diagnosing checks
6–11.

## Streaming output

An output with `streaming: true`. Causes the renderer to open an SSE
connection to the tool's `/stream` after the initial `/run`. Updates
arrive as `{output_key, value, done}` events.

## Sweep

A pass of the retention sweeper. Prunes old runs (per-tool
`retain_runs`) and hard-deletes soft-deleted artefacts. Runs every 6
hours; manual via `uv run pixie sweep`.

## Tool

A folder under `tools/` containing `tool.json`, `pyproject.toml`,
`main.py`, and `.venv/`. Runs as a child process of Pixie.

## Tool id

The folder name, also `tool.json.id`. Kebab-case. Used in URLs, run
records, and validation reports.

## Validator

`pixie/validator.py`. 11 mandatory checks + opt-in check 12. The
gatekeeper for sidebar visibility.

## ValidationReport

The output of the validator. A row in `validation_reports` keyed on
`(tool_id, timestamp)`. Drives the sidebar dot colour and the report
view when a failed tool is clicked.

## Warm-keep

The policy that keeps recently-used tool subprocesses alive for
`warm_keep_seconds` (default 300) so the next click is instant. Bounded
by `warm_keep_max` (default 5) global LRU cap.

## Workspace

A named sidebar group in `pixie.db` (`workspaces` table). One tool, many
workspaces.
