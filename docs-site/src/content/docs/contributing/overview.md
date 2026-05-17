---
title: How to contribute
description: The short version — issues, PRs, validator-first.
sidebar:
  order: 1
---

Issues and PRs welcome. Pixie is small, deliberately scoped, and meant
to stay that way — read [Out of scope](/Pixie/contributing/out-of-scope/)
first so we don't waste each other's time.

## Quick rules

1. **Validator-first.** Every change that touches a tool ends with
   `uv run pixie validate <id>` passing. Every change that touches the
   validator itself bumps the test fixture.
2. **No new frontend frameworks.** Tailwind, htmx, Alpine. That's it.
   No React, no build step.
3. **No new runtime dependencies** without a strong reason. The
   default `pyproject.toml` already pulls in a lot — see
   [Reference → Configuration](/Pixie/reference/configuration/).
4. **Type-annotate everything.** All function signatures. `pathlib.Path`
   over raw strings. Pydantic models for any JSON shape.
5. **British English in docs and UI strings.** "Colour", "behaviour",
   "centre".
6. **Comments explain why, not what.** Most functions need no
   comments at all.

See [Code style](/Pixie/contributing/style/) for the full list.

## Issue triage

| Label                | Means                                                  |
| -------------------- | ------------------------------------------------------ |
| `bug`                | Reproducible incorrect behaviour.                      |
| `validator`          | Validator emits wrong status or message.               |
| `renderer`           | Wrong UI for a declared input/output type.             |
| `skill`              | Skill misroutes, fails, or doesn't surface the report. |
| `tool`               | A bundled tool is broken.                              |
| `docs`               | Docs are wrong or missing.                             |
| `discussion`         | Open question, no work item.                           |
| `out-of-scope`       | Explicitly declined, see linked rationale.             |

## PR workflow

1. Fork the repo and branch.
2. `uv sync` to install dev deps.
3. Make your change.
4. `uv run pytest` until green.
5. If you changed any tool, `uv run pixie validate <id>` until green.
6. If you changed any input/output type, also run a smoke test in the
   browser — the type's renderer is the most likely thing to break.
7. Push and open a PR.

The PR template asks two questions:

- **What changed.** One sentence.
- **Why.** One sentence. (If it's a bug fix, link the issue.)

## Things we won't merge

See [Out of scope](/Pixie/contributing/out-of-scope/) for the full list.
The big ones:

- Auth, user accounts, multi-user.
- Cloud sync, telemetry, remote access.
- Docker for v1.
- JavaScript frameworks or a JS build step.
- Marketplace / registry / "publish" features.
- Any way to install dependencies from the dashboard UI.

## Read next

- [Dev environment](/Pixie/contributing/dev-setup/) — get a working
  development setup in 5 minutes.
- [Code style](/Pixie/contributing/style/) — the conventions.
- [Adding a new input/output type](/Pixie/contributing/new-type/) — the
  most common contribution.
- [Tests](/Pixie/contributing/tests/) — what's covered, how to add more.
