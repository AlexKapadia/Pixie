---
title: Runtime & subprocesses
description: How Pixie spawns, warm-keeps, and shuts down tool subprocesses.
sidebar:
  order: 2
---

This page is for "I want to understand exactly when my tool is alive and
when it dies." If you just want to write a tool, you can skip to
[Build a tool](/Pixie/build/anatomy/).

## The launcher

`pixie/launcher.py` owns every running tool subprocess. Its in-memory state
is roughly:

```python
{
  "lorenz-ode-solver":  (process, port=51234, last_used=...),
  "compound-interest":  (process, port=51235, last_used=...),
  ...
}
```

That dict is the single source of truth for "is this tool running right
now?" The dict resets on every Pixie restart — warm state is not
persisted.

## Spawn

When a request needs a tool that isn't in the dict, the launcher:

1. **Picks a free port.** Bind to `127.0.0.1:0`, read the OS-assigned port,
   release the binding. Ports are never reused within a Pixie session.
2. **Builds the env.** Inherits Pixie's `PATH`, scrubs out Pixie-internal
   variables, layers in the tool's `.env` (if present) via `python-dotenv`.
3. **Spawns the child.** `Popen(["<.venv>/bin/python", "main.py", "--port",
   str(port)], cwd=tool_path, env=env)`.
4. **Polls `/healthz`.** Up to 30 s at 100 ms intervals. The tool should
   bind its socket and return `{"ok": true}` quickly — anything slow is a
   smell.
5. **Fetches `/schema`.** Compares against on-disk `tool.json`. A drift
   warns in the launcher log but doesn't kill the tool — discovery already
   parsed disk; the running schema is for cross-checking.
6. **Registers.** The tool is now warm.

If anything in 1–5 fails, the tool is marked failed and its stderr is
captured for the error overlay. Subsequent clicks **re-attempt** — failures
aren't sticky, because you may have fixed something on disk between clicks.

## Warm-keep

A tool stays warm for `warm_keep_seconds` (per-tool, default 300) after its
last activity. Activity = a `/run` or `/stream` request. A background asyncio
task sweeps the dict every few seconds; any entry past its TTL is shut down.

The global cap `warm_keep_max` (default 5) prevents memory exhaustion.
When you'd exceed it, the launcher picks the LRU warm tool and shuts it
down to make room for the new one.

You can override `warm_keep_seconds` per-tool by editing `tool.json`. You
can pin a tool with the `pin-tool` skill (or by setting `tool_state.pinned =
1` directly) — pinned tools are exempt from LRU eviction but still respect
their TTL.

## Shutdown

Shutdown is two-phase:

1. **SIGTERM**, then wait up to 5 s for the process to exit.
2. **SIGKILL** if it didn't.

On Windows there's no SIGTERM; the launcher uses `CTRL_BREAK_EVENT` to
processes spawned with `CREATE_NEW_PROCESS_GROUP`. The "slow shutdown" path
is more common on Windows, and the validator records it as a `warn`.

A `SystemExit`/`KeyboardInterrupt` in Pixie itself triggers an orderly
shutdown of every warm tool.

## Resource limits

`max_memory_mb` and `max_runtime_seconds` from `tool.json` are enforced
**per spawn**:

- **POSIX**: `resource.setrlimit(RLIMIT_AS, ...)` for memory; a watchdog
  asyncio task kills the process on runtime overflow.
- **Windows**: Memory limits are not portable — only the runtime watchdog
  applies. Document this in your tool's README if memory is critical.

When a limit triggers, the user sees `ResourceLimitExceeded: memory` or
`...: runtime` in the output panel, with a "view stderr" disclosure.

## Failure modes you'll meet

| Symptom                                | Likely cause                                                        |
| -------------------------------------- | ------------------------------------------------------------------- |
| Tool never reaches `/healthz`          | `main.py` raises on import; uvicorn binds to a different port       |
| `/schema` drift warning                | You edited `tool.json` but not `main.py` (or vice versa)            |
| Run returns 422                        | Request body doesn't match input schema — usually a type mismatch   |
| Run returns 500 with no stderr         | The tool caught its own exception and returned a bad-shape response |
| Tool exits 0 immediately after spawn   | uvicorn isn't being called (`if __name__ == "__main__"` missing)    |
| LRU eviction during a long run         | `max_runtime_seconds` too low, or `warm_keep_max` too low           |

The [`debug-tool`](/Pixie/skills/diagnostics/#debug-tool) skill diagnoses
every one of these systematically — start there.

## Inspecting live state

Pixie exposes a JSON endpoint at `GET /api/launcher/state` (developer-mode
only) that returns the warm dict. It's useful for ad-hoc poking; the
[`pixie-status`](/Pixie/skills/diagnostics/#pixie-status) skill wraps it
nicely.

For a one-shot CLI view:

```bash
curl -s http://127.0.0.1:7860/api/launcher/state | jq
```

## Why subprocess, why not asyncio in-process?

Three reasons:

1. **Dependency isolation.** A tool may need `torch==2.0.1`; another may
   need `torch==1.13`. You cannot have both in one Python.
2. **Failure isolation.** A tool that segfaults its native code kills its
   own process, not Pixie.
3. **Resource accounting.** OS-level limits and accounting (CPU, memory,
   open files) are trivial against a subprocess and a nightmare inside
   asyncio.

The cost is ~150–300 ms of cold-start per tool. The warm-keep is exactly
what amortises that cost away.
