---
name: register-export-target
description: Registers a named export TARGET (destination folder plus default format) in pixie.db so future exports go there in one command. Use when the user asks to set up, configure, register, or define an export target, preset, or shortcut. Do NOT use for one-shot send (send-to-folder) or conversion (export-as-format).
allowed-tools: Bash, Read, Write, Edit
---

# Register a named export target (folder + default format)

You configure a reusable export target stored alongside `send-to-folder`'s destinations in `pixie.db.settings.export_destinations`. A target extends a plain destination with a default format, so future exports can write directly to it in one command. Pure config — no files are exported by this skill.

## Routing check (do this first)

- If the user wants to do a one-off send right now (no preset), switch to `send-to-folder` (no format conversion) or `export-as-format` (with format conversion + path).
- If the user wants to list / remove destinations only (no format preset), switch to `send-to-folder` in list/set mode.
- If the user is configuring a SECRET or API key for a tool, switch to `set-secret`.
- If the user is configuring a workspace, switch to `workspace-create` or `workspace-add-tool`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Storage

Same `settings.export_destinations` row used by `send-to-folder`. The value is a JSON map; each value can be EITHER a plain string (a path — backward compatible with `send-to-folder`) OR an object:

```json
{
  "Notes": "/Users/alex/Documents/Notes",
  "BlogAssets": {
    "path": "/Users/alex/blog/assets",
    "default_format": "png",
    "created_at": "2026-05-17T09:54:00Z"
  },
  "Reports": {
    "path": "/Users/alex/Documents/Reports",
    "default_format": "pdf"
  }
}
```

The object form is what this skill writes. The plain-string form is what `send-to-folder` writes when no default format is set.

## Steps

### 1. Mode A — List existing targets

```bash
uv run python -c "
import json, sqlite3, pathlib
conn = sqlite3.connect(pathlib.Path('pixie.db'))
row = conn.execute(\"SELECT value FROM settings WHERE key='export_destinations'\").fetchone()
data = json.loads(row[0]) if row else {}
for name, val in data.items():
    if isinstance(val, str):
        print(f'  {name:20s}  {val:60s}  (no default format)')
    else:
        print(f'  {name:20s}  {val[\"path\"]:60s}  default: {val.get(\"default_format\",\"-\")}')
"
```

Tell the user which entries are plain destinations (managed by `send-to-folder`) vs registered targets (with default format).

### 2. Mode B — Register / update a target

The user supplies `name`, `path`, and `default_format`. Validate each:

- `name`: non-empty, no path separators, max 32 chars.
- `path`: absolute (expand `~`); the destination folder may exist or will be created.
- `default_format`: one of the supported export formats from `DECISIONS.md` — the user is choosing this format up front, so it must be a real format. If they say "pdf", "png", "csv", "md", "xlsx", "json", "html", "wav", "mp3", "mp4", "geojson", "ical" etc., validate against the matrix.

If `default_format` is not in the global format vocabulary, REFUSE and list valid choices.

Note: the default format must still be SUPPORTED for the artefact's specific output type at export time — `export-as-format` does that check. Registering a target with `default_format=xlsx` is fine; it will work for tables and fail for audio.

Create the destination folder if missing (the user explicitly named it):

```bash
mkdir -p "<path>"
```

Windows PowerShell: `New-Item -ItemType Directory -Force "<path>"`.

Then write the entry:

```bash
uv run python -c "
import json, sqlite3, pathlib, sys, datetime
name, path, fmt = sys.argv[1], sys.argv[2], sys.argv[3]
conn = sqlite3.connect(pathlib.Path('pixie.db'))
row = conn.execute(\"SELECT value FROM settings WHERE key='export_destinations'\").fetchone()
data = json.loads(row[0]) if row else {}
data[name] = {
    'path': path,
    'default_format': fmt,
    'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
}
conn.execute(\"INSERT INTO settings(key, value) VALUES('export_destinations', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value\", (json.dumps(data, indent=2),))
conn.commit()
print({'ok': True, 'name': name, 'entry': data[name]})
" "<name>" "<path>" "<format>"
```

Confirm with one line:

> "Registered export target `<name>` → `<path>` (default format: `<fmt>`)."  
> Second line: "Future exports can reference it by name. See `send-to-folder` to send a specific artefact there."

### 3. Mode C — Remove a target

User supplies `--remove <name>`.

```bash
uv run python -c "
import json, sqlite3, pathlib, sys
name = sys.argv[1]
conn = sqlite3.connect(pathlib.Path('pixie.db'))
row = conn.execute(\"SELECT value FROM settings WHERE key='export_destinations'\").fetchone()
data = json.loads(row[0]) if row else {}
removed = data.pop(name, None)
if removed is None:
    print({'ok': False, 'reason': 'no such target'}); raise SystemExit(2)
conn.execute(\"INSERT INTO settings(key, value) VALUES('export_destinations', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value\", (json.dumps(data, indent=2),))
conn.commit()
print({'ok': True, 'removed': name})
" "<name>"
```

Confirm:

> "Removed export target `<name>`. The folder on disk is untouched."

Note: the folder itself is never deleted — this skill manages the registration only.

### 4. Mode D — Convert a plain destination into a registered target

If `send-to-folder` already created `<name>` as a plain string entry and the user wants to attach a default format, this skill upgrades it in place (reads the existing path, wraps it in the object form, adds `default_format`). Re-use Mode B with the existing path.

### 5. Settings page visibility

The Pixie settings page (`/settings`) reads the same `export_destinations` key and renders both plain entries and registered targets. The user does NOT need to know about the DB to use this — the dashboard exposes it. This skill is the CLI/chat equivalent.

### 6. Do NOT run the validator

This skill does not modify any tool.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
Format `<fmt>` is not a valid Pixie export format. Valid formats:
  txt md pdf docx html json csv tsv xlsx parquet yaml toml
  png svg jpg webp wav mp3 flac ogg mp4 webm gif tex
  geojson gpx kml ical jsonl patch zip
Pick one from this list.
```

```
Path `<path>` is not absolute. Use an absolute path (e.g. starting with `/` or `C:\`).
```

```
Name `<name>` is invalid. Use 1–32 characters, no slashes or backslashes.
```

```
No export target named `<name>`. Use Mode A (list) to see what's registered.
```

## Do NOT

- Do NOT export any files in this skill — it is pure config. Use `send-to-folder` or `export-as-format` to actually export.
- Do NOT delete the destination folder on disk when removing a target — only the registration is removed.
- Do NOT validate that the default format is supported for any specific artefact type — that's `export-as-format`'s job at export time.
- Do NOT register a target with a relative path.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
