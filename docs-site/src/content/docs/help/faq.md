---
title: FAQ
description: Common questions about running, sharing, and trusting Pixie.
sidebar:
  order: 1
---

## Is my data sent anywhere?

No. Pixie binds to `127.0.0.1` and refuses to bind to anything else.
There's no telemetry, no analytics, no error reporting. Every byte of
input you type and every byte of output a tool produces stays on your
machine.

The only exceptions are **tools that explicitly call external APIs**
(e.g. `rag-with-citations` calls Anthropic if you set the API key,
`whisper-transcription` downloads its model from HuggingFace on first
run). Those are choices the tool makes; Pixie's runtime doesn't.

## Do I need a Claude subscription?

You need [Claude Code](https://claude.ai/code) to use the bundled
skills for adding, editing, and debugging tools. You can hand-write
tools without Claude Code — every file format is documented in
[Build a tool](/Pixie/build/anatomy/).

Pixie itself has no relationship with Anthropic. Some tools that ship
in the cookbook call Anthropic's API; that's per-tool and optional.

## What if a tool breaks?

Three options:

1. From Claude Code: `Debug the foo tool` — triggers
   [`debug-tool`](/Pixie/skills/diagnostics/#debug-tool), which
   validates, reads the failing checks, proposes and applies a fix,
   then re-validates.
2. From the CLI: `uv run pixie validate foo` returns a structured
   report identifying the failing check and its details.
3. From the dashboard: click the tool's red sidebar dot — it shows the
   validation report inline.

If `debug-tool` can't fix it in two attempts, it stops and surfaces
both reports.

## Can I share tools with others?

Yes. Copy the tool folder, the recipient runs `uv sync` inside it. Or
use the [`share-tool`](/Pixie/skills/outputs/#share-tool) skill to
package it as a `.zip` (excluding `.venv/`, `.env`, and `.git/`); the
recipient runs [`import-tool`](/Pixie/skills/add-tools/#import-tool).

There's no central registry, no marketplace, no "publish" button —
sharing is a `.zip` and a `set-secret` on the other side.

## Why isn't this hosted?

Because it doesn't need to be, and your tools may touch local files or
credentials. The whole architecture is built around "the user already
has this machine and isn't going to spin up a SaaS account." A hosted
version of Pixie would be a different product — see
[Out of scope](/Pixie/contributing/out-of-scope/#authentication-user-accounts-multi-user).

## How does it handle tools that take ages to start?

Pixie's launcher polls `/healthz` for 30 s after spawn. Tools that need
longer (model downloads, heavy initialisation) should:

- Download/cache their model on **first** run lazily inside `/run`
  instead of at module import — so the first run is slow but `/healthz`
  is fast.
- Or set `validator_timeout_override` in `tool.json` to extend the
  validator's spawn timeout.

Once warm, subsequent runs are instant.

## How big can my outputs be?

Inline outputs (in `runs.outputs_json`) are capped at 64 KiB by
default (`inline_output_max_bytes`). Larger outputs spill to
`artefacts/<tool>/<run>/<filename>` and the response is rewritten to
point at the artefact endpoint.

Per-run total cap is 10 GiB (`max_artefact_bytes_per_run`). A watchdog
SIGKILLs any tool that exceeds it.

## My tool needs a GPU. Will Pixie use it?

Pixie's launcher inherits your `PATH` and passes through CUDA-related
env vars. If your venv has a CUDA-enabled PyTorch installed, your tool
will use the GPU.

We don't currently expose GPU memory limits to `setrlimit` — the only
enforced limits on POSIX are RAM and wall-clock.

## What's the difference between `category`, `workspace`, and `tag`?

- **Category** (in `tool.json`) — coarse default grouping. The "out of
  the box" placement (`finance`, `science/dynamics`, `nlp`, ...).
- **Workspace** (in `pixie.db`) — a user-defined sidebar group. A tool
  can be in many workspaces.
- **Tag** (in `tool.json` and `pixie.db`) — kebab-case keywords for
  filtering (`production`, `slow`, `costs-money`).

All three coexist. Use the one (or all three) that fits.

## Why isn't there an "install tool" button in the UI?

Because installing a tool means running `uv sync` (slow, blocking,
failure-prone) and then validating it (involves spawning a
subprocess). Both of those are bad fits for a UI button click.

Adding tools is a Claude Code skill responsibility. Pixie just renders
what's on disk.

## What Python versions are supported?

3.12+. We use modern type-system syntax (`|` unions, `Self`, `match`)
that isn't backportable. `uv python install 3.12` handles the upgrade
for you if your system Python is older.

## Why uv and not pip?

- `uv sync` is 10–100× faster than `pip install` for typical Pixie
  tools.
- The lock file (`uv.lock`) gives reproducible installs across machines
  without a separate `pip-tools` step.
- `uv python install` manages Python versions without `pyenv`.

Pixie's runtime doesn't depend on uv beyond what's installed in the
top-level repo; the per-tool `.venv/` directories work with `pip` too if
you really want to.

## Can I run multiple Pixie instances on one machine?

Yes — start each on a different port:

```bash
PIXIE_PORT=7860 uv run pixie &
PIXIE_PORT=7861 PIXIE_DB_PATH=./pixie-2.db uv run pixie &
```

Each instance needs its own DB and its own `artefacts/` root if you
want them fully isolated.

## How do I report a bug or request a feature?

[Open an issue](https://github.com/AlexKapadia/Pixie/issues). Read
[Out of scope](/Pixie/contributing/out-of-scope/) first for things we
won't accept.
