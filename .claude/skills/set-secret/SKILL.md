---
name: set-secret
description: Sets, changes, or clears one secret (API key, token, password) in a Pixie tool's .env. Use when the user asks to set, change, clear, or delete a secret, API key, token, or credential. Do NOT use to delete the tool (remove-tool), modify inputs (update-tool), or configure an export destination (register-export-target).
allowed-tools: Bash, Read, Glob
---

# Set a secret in a Pixie tool's `.env`

You are writing a secret value (API key, access token, password) into `tools/<tool_id>/.env`. This file is gitignored at both repo and tool level. The secret never goes into `pixie.db`, into chat output, into a log file, or back to the user.

## Critical rule about secret values

**Never print, repeat, echo, or surface the secret value back to the user.** This is the one place in the entire skill library where Claude must NOT confirm by repeating the user's input. The value goes from the user's message straight to disk via the Python one-liner below — at no point should Claude include the value in any output text, fenced block, summary, or "let me confirm I have ..." line.

The confirmation message after writing is exactly:

> `Secret <KEY> set for tool <tool_id>.`

Nothing more about the value.

## Routing check (do this first)

- This skill is for one tool at a time. If the user asks to set the same secret across many tools, do them one by one — refuse to batch silently.
- If the user wants to remove a secret rather than set one, tell them to delete the line from `tools/<tool_id>/.env` manually (or remove the file entirely). This skill writes only.

## Pre-flight: read the kill file

Before doing anything that might touch existing patterns, read `.build/KILL_FILE.md`. Any entry whose **Context** or **Symptom** matches your current task -> apply the documented **Fix** directly, do not re-debug from scratch.

## Steps

### 1. Gather the three inputs

You need:

1. The `tool_id` — which tool's `.env` to write.
2. The secret `key` — e.g. `OPENAI_API_KEY`.
3. The secret `value` — the actual token.

If the user supplied any of these in their first message, do not re-ask. If anything is missing, ask for each missing field separately. Ask for the **value last** and tell the user "paste the value alone — do not include `KEY=` in front of it."

### 2. Refuse if the value looks like an env-file fragment

If the user's value contains an `=` sign in suspicious position (e.g., `OPENAI_API_KEY=sk-...`, or anything matching `^[A-Z_][A-Z0-9_]*=`), STOP and surface the refusal block. This prevents the user from accidentally pasting multiple key=value pairs at once and leaking other keys into the wrong tool's `.env`.

### 3. Verify the tool exists

```bash
ls tools/<tool_id>/tool.json
```

If the file does not exist, STOP and tell the user the tool is not installed.

### 4. Check whether the secret is declared in `tool.json`

`Read` `tools/<tool_id>/tool.json` and look at the `secrets` array. If the user's `<KEY>` is not declared, warn:

> "Tool `<tool_id>` does not declare `<KEY>` in its `tool.json` `secrets` array. The value will be written to `.env` but the tool may ignore it. Proceed anyway? (yes/no)"

Wait for a yes. If no, STOP.

### 5. Write the secret to `.env`

Use a Python one-liner that reads any existing `.env`, updates the single key, and writes it back. The value comes from an environment variable so it never appears on a command line in process listings:

PowerShell (Windows):
```powershell
$env:PIXIE_SECRET_VALUE = '<the value>'
uv run python -c "import os, pathlib; p = pathlib.Path('tools/<tool_id>/.env'); lines = p.read_text(encoding='utf-8').splitlines() if p.exists() else []; key = '<KEY>'; lines = [l for l in lines if not l.startswith(key + '=')]; lines.append(key + '=' + os.environ['PIXIE_SECRET_VALUE']); p.write_text('\n'.join(lines) + '\n', encoding='utf-8'); print('written')"
Remove-Item Env:PIXIE_SECRET_VALUE
```

Bash (POSIX / Git Bash):
```bash
PIXIE_SECRET_VALUE='<the value>' uv run python -c "import os, pathlib; p = pathlib.Path('tools/<tool_id>/.env'); lines = p.read_text(encoding='utf-8').splitlines() if p.exists() else []; key = '<KEY>'; lines = [l for l in lines if not l.startswith(key + '=')]; lines.append(key + '=' + os.environ['PIXIE_SECRET_VALUE']); p.write_text('\n'.join(lines) + '\n', encoding='utf-8'); print('written')"
unset PIXIE_SECRET_VALUE
```

Substitute `<the value>` only at the very last moment when constructing the Bash command. Do not Edit or Write the value to any intermediate file. Do not echo the constructed command back as a code block with the value still inside — replace it with `<the value>` for any visible display.

### 6. Confirm completion

Exactly this line, nothing more:

> `Secret <KEY> set for tool <tool_id>.`

Tell the user the `.env` file is gitignored and that the value is loaded by the tool at runtime via `python-dotenv`. Do not summarise, do not repeat the value, do not show the file contents.

### 7. Do not run the validator

Setting a secret does not change the tool's contract. The validator is not the right tool here. If the user wants to test that the secret works, tell them to invoke the tool from the Pixie dashboard.

## On failure: append to the kill file

If you encounter an error NOT already in `.build/KILL_FILE.md`, append a new entry with the next `KILL-NNNN` id following the schema. Be terse -- root cause + one-line fix + one-line rule.

## Refusal templates

```
The value you gave me looks like it already contains a `KEY=value`
fragment (it starts with an identifier followed by `=`). I won't write
that as-is — it would either store a malformed value or, worse, leak
other keys into this tool's `.env`.

Give me the value alone, with the key as a separate piece. For example:
- key: OPENAI_API_KEY
- value: sk-abcd1234... (just the token, no `OPENAI_API_KEY=` prefix)
```

## Do NOT

- Do NOT echo, repeat, summarise, or quote the secret value back in chat.
- Do NOT log the value to any file other than the tool's `.env`.
- Do NOT pass the value on a literal command line — use an environment variable.
- Do NOT write the value to `pixie.db`. Pixie's database never stores secret values.
- Do NOT copy the value into `tool.json` or `main.py`.
- Do NOT batch this skill across multiple tools — one tool per invocation.
- Do NOT bind to `0.0.0.0` or any non-loopback interface.
- Do NOT add authentication or multi-user concepts.
- Do NOT invoke other Pixie skills programmatically.
