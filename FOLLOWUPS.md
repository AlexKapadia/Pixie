# Pixie Follow-up Issues

Triage results from Section 10 of the master fix prompt (branch `master-prompt-fixes`).
Items marked **FIXED** were resolved inline; the rest are deferred for future PRs.

## Fixed inline

- **(item 8) Two-column layout overflow below ~900px** — `pixie/static/pixie.css` near line 887: added `@media (max-width: 900px) { .pixie .tool-body[data-layout="form"] { grid-template-columns: 1fr; } }`.
- **(item 14) `_pixie_run_outputs` magic tag** — `pixie/db.py register_artefact` now raises `ValueError` if a caller passes `tags=["_pixie_run_outputs", ...]` with any `output_key` other than the reserved `"_pixie_run_outputs"`. The single legitimate internal write at `pixie/artefacts.py:458` is unaffected.

## Verified (no action needed)

- **(item 2) `htmx:oobErrorNoTarget` for `sidebar-dot-<tool_id>`** — already fixed in commit `be89abe` (fix(nav): hx-select on shell swaps + settings POST returns body partial). The sidebar dot spans in `pixie/templates/partials/sidebar.html:127-134` now carry `id="sidebar-dot-{{ tool_entry.tool_id }}"` on every branch of the status conditional, matching the target id emitted by the OOB swap in `pixie/routes/tool.py:162`.
- **(item 1) PAGEERR "Unexpected token" JS errors** — audited every `onclick`/`onchange` inline handler under `pixie/templates/**/*.html`. All use double-quoted attributes with internal single quotes; syntactically valid JS. The reported error is not reproducible from a static read. If it recurs, capture the exact stack and re-investigate; current candidates (`settings_global_body.html:27,52,72,123`, `tool_fragment.html:34`, etc.) are clean.
- **(item 7) Inline `<script>` blocks in output partials** — every chart/map/timeline/table partial under `pixie/templates/partials/outputs/*.html` wraps its render code in an immediately-invoked function expression and reads its data from a sibling `<script type="application/json">` that is parsed first. This works for both htmx swaps and full-page renders (the JSON `<script>` element exists by the time `document.getElementById` runs because DOM order guarantees it). No wrapping in `DOMContentLoaded` required.
- **(item 9) tool_settings.html json-enc audit** — `python tools/ci/check_form_json_enc.py` exits 0 ("All settings forms opt out of json-enc.").
- **(item 10) Theme `auto` round-trip** — verified `pixie/templates/partials/settings_global_body.html:27`: the `auto` radio value is preserved literally on persist; the resolved light/dark only feeds `Pixie.setTheme`. Round-trips correctly.
- **(item 12) Sweeper orphan-archived-flag heuristic** — RESOLVED upstream by Agent C's `archive_log` table, which is now the source of truth. No heuristic remains.
- **(item 13) Launcher port-bound assertion** — `pixie/launcher.py::_wait_healthy` (lines 372-394) already provides an implicit port-bound check: it fetches `http://127.0.0.1:{running.port}/healthz`, and a 200 response is only possible if the child bound the exact port the launcher allocated. If the child bound a different port (or none), the loop times out with `ToolSpawnTimeout`. No additional explicit assertion needed.

## Deferred (need follow-up PRs)

- **(item 3) Header "running" pill never clears** — `pixie/templates/partials/header.html:9-17` server-renders the `<span class="badge badge--running">` based on `tool.status`. There is no OOB swap of the header pill after run completion (`pixie/routes/tool.py::_output_response_with_chrome` only swaps sidebar dot + history). Fix: add `id="header-status-pill"` to the pill span, then emit a matching OOB span (with the current `tool.status` recomputed post-run) in `_output_response_with_chrome`. Requires also handling the `warm`/`dormant`/`failed` transitions; ~15-line change.
- **(item 4) Theme context: single source of truth** — multiple routes read `settings.theme` directly outside `_base_context`:
  - `pixie/routes/dashboard.py:192` (inside `_base_context` itself — OK)
  - `pixie/routes/library.py:207`
  - `pixie/routes/tool.py:140`
  - `pixie/routes/tools_grid.py:275`
  - `pixie/routes/settings.py:115,203,393,474,479`
  Refactor: have every render path call a shared `_base_context` helper that produces `theme`. Currently `dashboard.py` and `settings.py` each define their own `_base_context`. Consolidate into one location (e.g. `pixie/routes/_context.py`) and have library/tool/tools_grid import and use it.
- **(item 5) `persisted_settings` mandatory in `_base_context`** — add an assertion (or safe fallback to `{}`) in the consolidated `_base_context` once item 4 lands.
- **(item 6) Theme toggle fire-and-forget race** — documented only per master prompt. The `Pixie.persistPreference('theme', this.value)` call in `settings_global_body.html:27` is async fire-and-forget; if the user changes theme rapidly the last write may not be the last sent. Acceptable for now; revisit if user reports stale persistence.
- **(item 11) `_to_static` `**_ignored`** — `pixie/exporters/charts.py:190` accepts `**_ignored` because callers at lines 337/340/343 splat `**kw` from the exporter registry (which passes `prov`, `output_key`, `spec`, plus potentially other registry-managed kwargs). The `**_ignored` is defensive, not bug-hiding. Leave in place. If a future audit wants to tighten, enumerate the exact kwargs the registry passes and switch to explicit parameters; not worth the churn today.
