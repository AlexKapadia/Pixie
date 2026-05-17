---
title: Code style
description: Conventions we hold to in Pixie's source.
sidebar:
  order: 3
---

These are conventions, not laws. PRs that violate them are reviewed on
the merits — but if you don't have a reason to deviate, follow them.

## Python

- **Python 3.12+**. We use modern syntax: `match`, `|` union types,
  `Self`.
- **Type annotations on every function signature.** Module-level
  variables don't need them. Internal helpers can use sparingly.
- **`pathlib.Path` everywhere**. Never raw strings for paths.
- **`pydantic` models for any JSON shape**. The schema is the
  documentation.
- **`async def` for I/O**. Synchronous DB calls live in
  `asyncio.to_thread` (see `pixie/db.py` for the pattern).
- **`httpx.AsyncClient` for HTTP** in async paths. Never `requests`.
- **`logging` for output**. Never `print()` in library code (the
  `SecretMaskingFilter` only sees `logging` calls).
- **Short functions.** If a function passes 40 lines, look for a
  refactor.
- **British English for user-facing strings.** Code identifiers can be
  whichever (most are American per Python convention).

### Comments

Default: don't write any. Add a comment when:

- A constant has a non-obvious source ("from Black-Scholes 1973, eq. 7").
- An algorithm has a non-obvious performance characteristic ("O(n²) is
  fine here — n is bounded by 20").
- A workaround exists for a specific issue ("`# Windows
  CTRL_BREAK_EVENT shenanigans, see #142`").

Don't restate what the code does. Don't reference current tasks
("# added for the X flow") — those belong in commit messages.

### Identifier conventions

- `tool_id`, not `tid` or `id_`.
- `subprocess`, not `proc`.
- `validation_report`, not `report` (the latter is ambiguous in this
  codebase).
- `run_id`, not `rid`.

No abbreviations except the universal ones (`db`, `url`, `id`, `json`,
`http`).

### Error handling

- Raise specific exceptions: `ValueError`, `RuntimeError`,
  `FileNotFoundError`. Avoid bare `Exception`.
- At HTTP boundaries, convert exceptions to `HTTPException(status,
  detail=...)`.
- Don't swallow exceptions silently. `except Exception: pass` is a smell;
  log the exception unless you specifically want it discarded.
- Tools' errors are captured by the proxy and surfaced to the user. Don't
  print stack traces to stderr unless something has gone genuinely wrong.

## Templates and HTML

- All user-facing strings go through Jinja templates, not Python string
  literals. `templates/partials/` is the right home.
- Use the Tailwind utility classes already in use. Don't introduce a new
  spacing scale.
- Sentence case for buttons and labels ("Run tool", not "Run Tool").
- No emojis in the UI itself.
- One partial per input type, one per output type — no monolithic
  switches.

## JavaScript

- **Vanilla JS only.** No bundler. No npm packages beyond what's already
  in `pixie/static/vendor/`.
- Hang helpers off `window.Pixie`. Don't pollute the global namespace.
- Use `Pixie.initOnSwap(fn)` for anything that needs to bootstrap on
  initial load *and* after htmx swaps.
- Charts: call `Pixie.makeChart(el, data, layout)` so theme switching
  works.
- Maps: call `Pixie.makeMap(el, opts)` so the base tile layer is
  consistent.

## SQL

- Migrations are `ALTER TABLE` statements via `_safe_alter()`. They must
  swallow "duplicate column" errors so re-running is a no-op.
- Indexes are explicit. Don't rely on SQLite to invent good ones.
- `WAL` mode is mandatory; the connection helper sets it.

## Tests

- `pytest` only. No `unittest`.
- Test names describe behaviour, not implementation: `test_validator_passes_example_tool`,
  not `test_validate_tool_function`.
- Fixtures over inline setup. `tests/conftest.py` is the home.
- Heavy tests are marked (`@pytest.mark.perf`, etc.) so they skip by
  default.

## Commit messages

Conventional-commit-ish but informal:

```text
feat(validator): add check 12 reference-fixture comparison
fix(launcher): handle Windows CTRL_BREAK_EVENT for warm shutdown
docs(build): clarify chart_scatter series shape
refactor(db): consolidate prune_runs and prune_starred_aware
test(integration): add cancel-flow test against example tool
```

PR titles should follow the same shape. Squash-merge to main keeps
history clean.

## What we don't do

- **No print debugging in committed code.** Use `logging.debug(...)` if
  you must keep it.
- **No `# TODO` comments.** Open an issue.
- **No magic strings.** If the renderer dispatches on `"chart_line"`,
  the discriminator lives in a constant, not scattered through the
  code.
- **No hidden side effects.** Functions that mutate global state are
  named obviously (`init_db`, `register_global_filter`).

If in doubt: imitate the code around the spot you're editing. Style
across the codebase is genuinely consistent and it's an asset.
