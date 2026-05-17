---
name: send-to-folder
description: Sends a Pixie output to a NAMED destination folder (e.g. Notes, Dropbox, Inbox) registered in settings.export_destinations. Use when the user asks to send, file, route, drop, or save an output INTO a named recurring location. Do NOT use for a one-off path (copy-output-to), clipboard (copy-to-clipboard), or register a destination (register-export-target).
allowed-tools: Bash, Read, Write, Edit
---

# Send a Pixie output to a named destination folder

You maintain a small map of named destinations (e.g. `Notes → ~/Documents/Notes`, `Inbox → ~/Dropbox/Inbox`) in `pixie.db` under `settings.export_destinations` (JSON map of `{name: path}`). The skill has three modes:

1. **List** current destinations.
2. **Set / remove** a named destination.
3. **Send** a specific artefact to a named destination.

The artefact is copied as-is (no conversion). For format conversion to a destination, the user should use `export-as-format` and pick a path inside the destination folder directly, OR use `register-export-target` to pair a destination with a default format.

## Routing check (do this first)

- If the user wants a ONE-OFF destination path (not saved for reuse), switch to `copy-output-to`.
- If the user wants format conversion (PNG → PDF etc.), switch to `export-as-format`.
- If the user wants to pair a destination with a default format for repeated use, switch to `register-export-target`.
- If the user wants to open the artefacts folder in their file browser, switch to `open-artefacts-folder`.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Storage

`pixie.db` has a `settings` key/value table. Read and write the key `export_destinations` as JSON, e.g.:

```json
{
  "Notes": "/Users/alex/Documents/Notes",
  "Inbox": "/Users/alex/Dropbox/Inbox"
}
```

Helper SQL:

```sql
-- read
SELECT value FROM settings WHERE key = 'export_destinations';
-- write
INSERT INTO settings(key, value) VALUES('export_destinations', ?)
  ON CONFLICT(key) DO UPDATE SET value = excluded.value;
```

## Steps

### Mode A — List destinations

```bash
uv run python -c "
import json, sqlite3, pathlib
conn = sqlite3.connect(pathlib.Path('pixie.db'))
row = conn.execute(\"SELECT value FROM settings WHERE key='export_destinations'\").fetchone()
print(json.dumps(json.loads(row[0]) if row else {}, indent=2))
"
```

If empty, tell the user there are no destinations yet and show how to add one (Mode B).

### Mode B — Set / remove a destination

The user supplies `name` + `path` (set), or just `name` + `--remove` (delete).

Validate the path:
- Must be absolute (expand `~` to the home dir).
- Parent must exist; the destination folder itself may exist or not (create it if missing — folder creation IS allowed because the user explicitly named it).

```bash
mkdir -p "<path>"
```

On Windows PowerShell: `New-Item -ItemType Directory -Force "<path>"`.

Then update the JSON:

```bash
uv run python -c "
import json, sqlite3, pathlib, sys
name, path = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None
conn = sqlite3.connect(pathlib.Path('pixie.db'))
row = conn.execute(\"SELECT value FROM settings WHERE key='export_destinations'\").fetchone()
data = json.loads(row[0]) if row else {}
if path is None:
    data.pop(name, None); action = 'removed'
else:
    data[name] = path; action = 'set'
conn.execute(\"INSERT INTO settings(key, value) VALUES('export_destinations', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value\", (json.dumps(data),))
conn.commit()
print({'ok': True, 'action': action, 'name': name, 'destinations': data})
" "<name>" "<path-or-omit-for-remove>"
```

Confirm with one line:

> "Destination `<name>` set to `<path>`."  
> or  "Removed destination `<name>`."

### Mode C — Send an artefact to a named destination

#### C.1 Resolve the destination name

Read the map (Mode A query). If the user's name is not in it, STOP — list available destinations and ask which to use, or suggest setting it via Mode B.

#### C.2 Resolve the artefact

Same as `copy-output-to`:

```bash
curl -s "http://127.0.0.1:8765/api/artefacts?q=<query>&limit=20"
```

If zero matches, STOP — suggest `find-output` or `list-outputs`. If multiple, list and ask.

#### C.3 Decide the filename (collision handling)

Default filename = artefact's original filename. If the destination already contains a file with that name:

- Generate a suffix: `<stem>-<run_id_short>.<ext>`. If THAT also exists, append a short timestamp: `<stem>-<run_id_short>-<HHMMSS>.<ext>`.
- Never silently overwrite. If the user passed `--overwrite`, allow it; otherwise the suffix rule applies.

#### C.4 Confirm Pixie is reachable

```bash
curl -s http://127.0.0.1:8765/api/healthz
```

If reachable, fetch via the API (preferred — `Content-Disposition` gives the right filename and integrity hash is verifiable):

```bash
curl -s -f -o "<dest>/<safe-name>" "http://127.0.0.1:8765/api/artefacts/<id>/file"
```

If Pixie is offline, fall back to direct file read (same as `copy-output-to` Step 4b — query `artefacts.rel_path`, then `shutil.copy2`).

#### C.5 Verify the copy

Compute sha-256 of the destination and compare to the row in `artefacts`:

```bash
uv run python -c "
import hashlib, pathlib, sqlite3, sys
p = pathlib.Path(sys.argv[1])
h = hashlib.sha256(p.read_bytes()).hexdigest()
conn = sqlite3.connect(pathlib.Path('pixie.db'))
expected = conn.execute('SELECT sha256, size_bytes FROM artefacts WHERE id = ?', (int(sys.argv[2]),)).fetchone()
print({'ok': h == expected[0] and p.stat().st_size == expected[1], 'sha256': h, 'expected_sha256': expected[0]})
" "<dest>/<safe-name>" "<id>"
```

If `ok` is false, STOP — surface a corruption warning and leave the file in place for inspection.

#### C.6 Confirm

One line:

> "Sent artefact `<name>` from run `<run_id_short>` of `<tool_id>` to destination `<name>` (`<full-path>`, sha-256 verified)."

### Do NOT run the validator

This skill does not modify any tool.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
No destination named `<name>`. Current destinations:
  <listing>
Use `send-to-folder <name> <path>` to add one, or pick from the existing names.
```

```
Path `<path>` is not absolute. Use an absolute path (e.g. starting with `/` or `C:\`)
so the destination is unambiguous.
```

```
Parent directory `<parent>` does not exist. Create it first, then rerun.
```

```
SHA-256 mismatch after copy — destination file does not match the source.
The file has been left in place for inspection but is corrupt. Do not use it.
```

## Do NOT

- Do NOT silently overwrite an existing file at the destination — use the suffix rule or require `--overwrite`.
- Do NOT modify the source artefact.
- Do NOT register a destination with a relative path — refuse and ask for an absolute path.
- Do NOT silently confirm a corrupt copy — sha-256 mismatch is a hard stop.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT write the `export_destinations` key from any other skill — this is the owner.
- Do NOT run the Pixie validator.
- Do NOT invoke other Pixie skills programmatically — name them and stop.
