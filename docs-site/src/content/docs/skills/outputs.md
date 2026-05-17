---
title: Runs, outputs & exports
description: List runs, find artefacts, label & star, export runs and reports, share tools.
sidebar:
  order: 5
---

This is the large family of skills that handles **what came out of a
run** — the artefacts on disk, the run history in SQLite, and getting
either of them elsewhere.

## Inspecting

### view-runs

<span class="skill-pill">read-only</span>

**Trigger:** "Show the runs of foo", "What did foo do last?", "List the
last 10 runs of bar".

Lists runs of one named tool with inputs (truncated), status,
duration, and tail of outputs. Use this when you remember "I ran X
yesterday and got Y back" and want to find that specific row.

### list-outputs

<span class="skill-pill">read-only</span>

**Trigger:** "Show all outputs", "List saved files", "What artefacts do
I have?"

Lists artefact rows from `pixie.db` across all tools, optionally
filtered by tool / mime / starred / label. Returns paths and sizes.

### find-output

<span class="skill-pill">read-only</span>

**Trigger:** "Find PNGs", "Look for an artefact called transcript",
"Where's the file with 'budget' in the name?"

Substring search across filename, label, and tags. Use when you don't
know which tool produced the file.

### view-logs

<span class="skill-pill">read-only</span>

**Trigger:** "Show stderr for foo", "What did the tool log?", "Tail the
output".

Tails the warm tool's stderr ring buffer (default 64 KiB) or fetches
captured logs from a past run.

### audit-disk-usage

<span class="skill-pill">read-only</span>

**Trigger:** "How much disk?", "What's taking space?", "Audit Pixie's
footprint".

Per-tool report: `.venv/` size, `data/` size, models cache size,
artefacts size. Sorted largest-first. Flags archive candidates.

## Labelling

### label-run

<span class="skill-pill">non-destructive</span>

**Trigger:** "Label this run 'final-report'", "Name run xyz the
production version".

Sets `runs.label`. Labelled runs are exempt from age-based pruning, so
this also protects them from the retention sweeper.

### star-run

<span class="skill-pill">non-destructive</span>

**Trigger:** "Star this run", "Favourite that one", "Pin run xyz".

Sets `runs.starred = 1`. Same effect as `label-run` re: pruning, plus
the run gets a star icon in the history dropdown.

## Exporting

### export-run

<span class="skill-pill">non-destructive (writes a zip)</span>

**Trigger:** "Export run xyz", "Download the data from this run", "Zip
up the last run of foo".

**Steps:**

1. Resolve run id (accepts short prefix).
2. Verify Pixie is running (the export endpoint needs live DB access).
3. Refuse to overwrite the target zip unless `--force`.
4. Stream the zip from `/api/runs/<run_id>/export`.
5. Verify with `zipfile.testzip()`.

The zip contains `inputs.json`, `outputs.json`, `report.md`, and an
`artefacts/` directory.

### export-run-as-report

<span class="skill-pill">non-destructive</span>

**Trigger:** "Generate a report for run xyz", "Write up the foo run as
markdown".

Same as `export-run`, but rendered markdown report (`report.md` plus
`assets/`) instead of raw JSON. Use when you want something a human
will read.

### export-as-format

<span class="skill-pill">non-destructive</span>

**Trigger:** "Convert this output to CSV", "Export the chart as SVG",
"Save the audio as MP3".

Converts a single artefact between formats via the server-side
exporter. Supported: PNG/SVG/PDF for charts, XLSX/CSV/Parquet for
tables, MP3 for audio.

### bulk-export

<span class="skill-pill">non-destructive</span>

**Trigger:** "Export all runs from this week", "Download every run of
foo", "Bulk export starred runs".

Filters a set of runs, then bundles all their artefacts into one
server-side zip. Use this instead of looping `export-run`.

### copy-output-to

<span class="skill-pill">non-destructive</span>

**Trigger:** "Save this image to `/path/to/somewhere`", "Copy the CSV
to my Downloads folder".

One-shot byte-for-byte copy of a single artefact to a path you supply.
For named recurring destinations, use `send-to-folder` and
`register-export-target`.

### copy-to-clipboard

<span class="skill-pill">non-destructive</span>

**Trigger:** "Copy this text", "Put the JSON on the clipboard", "Yank
that markdown".

Copies a small textual output (text, markdown, number, boolean, json,
csv, kv, log) to the system clipboard. Binary outputs go via
`export-as-format` instead.

### send-to-folder

<span class="skill-pill">non-destructive</span>

**Trigger:** "Send this to Dropbox", "Route to my Notes folder", "File
under reports".

Sends an output to a **named destination folder** registered in
`settings.export_destinations`.

### register-export-target

<span class="skill-pill">non-destructive (writes settings)</span>

**Trigger:** "Set up a 'reports' export target", "Register Dropbox as
a destination".

Adds a named target (folder path + default format) to
`settings.export_destinations` so future exports go there in one
command.

### open-artefacts-folder

<span class="skill-pill">non-destructive (opens file browser)</span>

**Trigger:** "Show me where the files are", "Open the artefacts folder
in Finder", "Reveal in Explorer".

Opens the artefacts directory in the OS file browser (Explorer /
Finder / `xdg-open`). Optionally scoped to a tool or run.

## Cleanup

### clear-old-outputs

<span class="skill-pill">destructive</span>

**Trigger:** "Clear runs older than 30 days", "Sweep the run history",
"Prune old artefacts".

Runs the retention sweeper. Walks `runs` and `artefacts`, deletes those
older than `--older-than` (default 30d) **except** starred and
labelled. Dry-run by default; `--apply` commits.

Equivalent to `uv run pixie sweep --apply --older-than 30d`.

## Sharing

### share-tool

<span class="skill-pill">non-destructive (writes a zip)</span>

**Trigger:** "Share the foo tool", "Package bar to send to someone",
"Zip up the tool".

Packages a tool's source code into a `.zip`. **Excludes**:

- `.venv/` (platform-specific)
- `.env` (secrets)
- `.git/` (irrelevant)
- `data/` (often large)

Recipients install with `import-tool`. They run `uv sync` themselves to
rebuild `.venv/` and `set-secret` to set their own credentials.

The companion install side is [`import-tool`](/Pixie/skills/add-tools/#import-tool).
