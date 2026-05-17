---
title: Code style
description: Light preferences — none of these are hard rules.
sidebar:
  order: 3
---

These are preferences that keep the codebase consistent. None of them
will block a PR on their own. If you have a reason to deviate, deviate
— just say so in the PR description.

## Python

- Python 3.12+ is the floor, so modern syntax is fine.
- Type annotations are nice to have where they help — especially on
  public APIs and anything that crosses a module boundary.
- `pathlib.Path` reads better than raw string paths.
- `pydantic` models for JSON shapes save a lot of guard code.
- `httpx` over `requests` for async paths (there's already an
  `httpx.AsyncClient` in the runtime).
- Short functions are easier to read than long ones; nothing magic
  about 40 lines.
- Use `logging` over `print` so log filters can see your output.

## Comments

Write them when they help. Default to none. If the code is clear, a
comment is noise. If a constant has a non-obvious source or there's a
workaround for a specific bug, say so in a line of comment.

## Templates and HTML

- Server-rendered Jinja under `pixie/templates/`. Tailwind utility
  classes already in use.
- Sentence case for buttons and labels.
- One partial per input/output type — keeps the renderer dispatch
  trivial.

## JavaScript

- Vanilla JS, hung off `window.Pixie`. No bundler.
- Use `Pixie.initOnSwap(fn)` for anything that needs to bootstrap on
  initial load *and* after htmx swaps.
- Charts: `Pixie.makeChart(el, data, layout)` so theme switching
  works.
- Maps: `Pixie.makeMap(el, opts)` so base layers stay consistent.

## SQL

- Migrations are `ALTER TABLE` via `_safe_alter()` so re-running is a
  no-op.
- Explicit indexes — don't rely on SQLite to guess.
- WAL mode is on by default; the connection helper sets it.

## Tests

- `pytest`.
- Test names describe behaviour, not implementation.
- Fixtures live in `tests/conftest.py`.
- Heavy tests get a marker (`perf`, `visual`, `a11y`, `e2e`) so they
  skip by default.

## Spelling

The codebase mostly uses British English in user-facing strings
("colour", "behaviour", "centre"). Stick with that for consistency in
new strings, but it's not worth a PR to flip "color" → "colour" on
existing code.

## Commit messages

Conventional-commit-ish, informal. The shape:

```text
feat(area): add the thing
fix(area): handle the edge case
docs(area): clarify the thing
refactor(area): move things around
test(area): cover the thing
```

PR title in the same shape. Squash-merge keeps history tidy.

## When in doubt

Look at the code around the spot you're editing and follow that. Style
consistency in any one file matters more than global rules.
