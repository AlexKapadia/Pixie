# Reference Fixtures — Accuracy Validation (Check #12)

Pixie's validator runs eleven checks that prove a tool spawns cleanly,
responds on `/run`, and conforms to its declared schema. Check #12
goes one step further: it asks **"does the tool compute the right
answer?"**

## Where the fixtures live

Every tool _may_ ship a `reference/` folder at its root:

```
tools/<tool_id>/
├── tool.json
├── pyproject.toml
├── main.py
├── data/
└── reference/
    ├── fixture_<name>.json   # one per scenario
    ├── tolerance.yaml        # optional shared config
    └── README.md             # optional, free-text provenance
```

If `reference/` is missing, check #12 reports `skip` (not `fail`).
If `reference/` exists but has no `fixture_*.json` files, same.

## Writing a fixture

A fixture is a small JSON file with the schema:

```json
{
  "name": "Basic 10-year run, 5% annual, monthly compounding",
  "source": "Excel workbook compound-interest.xlsx, sheet 'Scenario A'",
  "inputs": {
    "principal": 10000,
    "annual_rate": 5,
    "years": 10,
    "compounding": 12
  },
  "expected_outputs": {
    "final_value": 16470.09,
    "yearly_breakdown": {
      "columns": ["year", "balance"],
      "rows": [[0, 10000.00], [1, 10511.62]]
    }
  },
  "tolerance": {
    "final_value": { "rtol": 1.0e-4 }
  },
  "tags": ["happy-path", "monthly-compounding"]
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Short — appears in the report. |
| `source` | no | Free-text provenance (workbook + sheet, DOI + table, etc). |
| `inputs` | yes | Validates against the tool's input schema. |
| `expected_outputs` | yes | Output-key → expected value. Subset of declared outputs is fine. |
| `tolerance` | no | Per-output overrides; highest priority in the hierarchy. |
| `skip_reason` | no | Mark a known-failing fixture as `skip` (paper trail without removal). |
| `tags` | no | Drives `--tag` filtering. |
| `validator_timeout_override` | no | Per-fixture seconds cap for slow scenarios. |

## The four-level tolerance hierarchy

For any (output_key, output_type) pair, tolerance is merged
**highest priority first** (later sources never overwrite earlier
ones):

1. **Fixture override** — `fixture.tolerance[output_key]`
2. **Project override** — `tolerance.yaml::overrides[output_key]`
3. **Project default by type** — `tolerance.yaml::defaults[output_type]`
4. **Built-in default by type** — `pixie.comparators._base.BUILTIN_DEFAULTS`

The merge is **shallow on the inner dict**: an override
`{ rtol: 1e-4 }` for a table replaces only `rtol`; `compare` and
`float_atol` continue to come from the layer below.

## `tolerance.yaml` shape

```yaml
defaults:
  number: { rtol: 1.0e-6, atol: 1.0e-9 }
  table:  { compare: rows_unordered, float_rtol: 1.0e-5 }
  image:  { compare: ssim, min_ssim: 0.97 }

overrides:
  final_value: { rtol: 1.0e-4 }     # only this output key

options:
  on_extra_output_key: warn         # warn | fail | ignore
  on_missing_expected_key: fail     # warn | fail | ignore
  truncate_diff_chars: 400
```

Any field is optional. Invalid `compare` values, unknown keys, or
wrong types are collected and surfaced as a single check #12 fail with
all problems listed.

## Comparator coverage

There is one default comparator per declared output type (39 total).
Highlights:

- **number** — `math.isclose(rel_tol=rtol, abs_tol=atol)`. Booleans
  are refused on purpose.
- **table** — column names equal, rows sorted by key then per-cell
  compared (string-exact, numeric-isclose, null-aware).
- **chart_line / bar / area / scatter / radar** — data-only; series
  matched by name; never renders pixels.
- **map_points / heatmap / polygons** — coordinates rounded to 4 d.p.
  (~11m) and compared as a set.
- **image / image_grid / image_compare** — SSIM via scikit-image with
  `min_ssim` threshold. Degrades to `sha256+size` if scikit-image is
  not installed; the diff metric tags the degradation.
- **audio** — mel-spectrogram L2 distance via librosa with
  `max_l2` threshold. Degrades to `sha256+size` if librosa is missing.
- **file** — sha256 by default; mime-dispatched for PDF
  (pdfplumber text equal, degrades to sha256), JSON (deep), CSV
  (table comparator).
- **video** — `skip` by default; opt in via
  `tolerance.video.compare: per_frame_ssim_mean` (frame decode requires
  ffmpeg; we degrade to size+sha256 if missing).

## Heavy dependencies (`pixie[accuracy]`)

scikit-image, librosa, pdfplumber, pillow, numpy are optional. They
are installed via:

```
uv pip install pixie[accuracy]
```

Without them the relevant comparators degrade to size+sha256 and tag
the diff's metric (e.g. `degraded: skimage not installed; pip install
pixie[accuracy] for full SSIM`) so the report never silently passes.

## CLI

```
pixie validate <tool_id>                         # full pipeline, 12 checks
pixie validate <tool_id> --reference-only        # skip checks 8-10; run only #12
pixie validate <tool_id> --fixture basic         # filter by fixture name
pixie validate <tool_id> --fixture 'fixture_*'   # glob
pixie validate <tool_id> --tag happy-path        # filter by tags
pixie validate <tool_id> --update-fixtures       # dry-run preview
pixie validate <tool_id> --update-fixtures --yes # commit the rewrite
```

`--update-fixtures` overwrites every fixture's `expected_outputs` with
whatever the live tool currently returns — useful when you've
intentionally changed model behaviour. It refuses to commit without
`--yes` and appends a timestamped note to the fixture's `source`.

## HTTP

```
GET  /api/tools/{id}/reference-fixtures   # picker payload
POST /api/tools/{id}/reference-check      # run check #12
```

POST body (all optional):

```json
{
  "fixtures": ["fixture_basic.json"],
  "tags": ["happy-path"],
  "update_expected": false,
  "yes": false
}
```

Same JSON shape as the existing `GET /api/tools/{id}/validate`, so
skills and the dashboard can reuse rendering code.

## Two worked examples

### Excel-derived fixture

A finance tool's `compound-interest` fixture pulls each scenario's
input + final cell from the original workbook. Tolerance loosens to
`rtol=1e-4` because Excel's displayed precision is 2dp:

```json
{
  "name": "Scenario A — base case",
  "source": "Excel compound-interest.xlsx sheet 'Scenario A'",
  "inputs": { "principal": 10000, "annual_rate": 5, "years": 10, "compounding": 12 },
  "expected_outputs": { "final_value": 16470.09 },
  "tolerance": { "final_value": { "rtol": 1.0e-4 } }
}
```

### Paper-reported metrics

A model that reports F1 to 2 sig figs in the source paper:

```json
{
  "name": "Table 3 row 2 (BERT-base, GLUE/MNLI)",
  "source": "Devlin et al. 2018 Table 3 row 2",
  "inputs": { "model": "bert-base", "task": "mnli" },
  "expected_outputs": { "f1": 0.846 },
  "tolerance": { "f1": { "rtol": 5.0e-3 } }
}
```

The fixture-level `rtol` overrides whatever `tolerance.yaml` sets for
the `number` type globally.
