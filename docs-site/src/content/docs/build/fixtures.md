---
title: Fixtures & reference validation
description: How to ship known inputs and expected outputs for the opt-in 12th validator check.
sidebar:
  order: 7
---

The validator's first 11 checks verify the **contract**: schema is
parseable, sample run succeeds, output shape matches. They do not check
that your tool returns the **right answer**.

Check 12 — `reference_fixtures_match` — is opt-in. Drop a `reference/`
folder into your tool with known inputs and expected outputs, and the
validator runs each fixture and compares the response with type-aware
comparators.

## Folder layout

```text
tools/my-tool/
├── tool.json
├── pyproject.toml
├── main.py
└── reference/
    ├── fixture_basic.json
    ├── fixture_edge_case.json
    └── tolerance.yaml          # optional, see below
```

Each `fixture_*.json` contains the inputs and expected outputs:

```json
{
  "name": "Basic compound interest",
  "inputs": {
    "principal": 10000,
    "annual_rate": 5,
    "years": 10,
    "compounding": 12,
    "monthly_contribution": 0,
    "inflation_adjusted": false
  },
  "expected_outputs": {
    "final_value": 16470.09,
    "total_contributions": 10000,
    "total_interest": 6470.09
  }
}
```

The validator POSTs `inputs` to `/run`, then compares each
`expected_outputs` key against the response.

## Tolerance

Different output types need different comparison strategies. Defaults:

| Output type        | Comparator                         | Default tolerance         |
| ------------------ | ---------------------------------- | ------------------------- |
| `number`           | absolute or relative tolerance     | 1e-6 abs OR 1e-4 rel      |
| `text`, `markdown` | exact string match                 | —                         |
| `table`            | cell-wise, with numeric tolerance  | 1e-6 abs                  |
| `kv`               | key-by-key                         | 1e-6 abs for numbers      |
| `chart_*`          | series shape + numeric values      | 1e-3 rel                  |
| `image`            | size + SHA256 (default), histogram distance (with `[accuracy]` extras) | — |
| `audio`            | size + SHA256, spectral distance (with `[accuracy]` extras)            | — |
| `file` (PDF)       | size + SHA256, text diff (with `[accuracy]` extras)                    | — |
| any other          | size + SHA256                      | exact                     |

Heavy comparators are gated by an optional dependency group. Install with:

```bash
uv sync --extra accuracy
```

This pulls in `scikit-image`, `librosa`, and `pdfplumber`. Without these,
binary outputs are compared by SHA-256 only — exact-match for
deterministic tools, useless for stochastic ones. The validator flags
this with a `warn` so you know you're getting weaker accuracy.

## `tolerance.yaml`

Override the defaults per output key:

```yaml
# tools/my-tool/reference/tolerance.yaml
final_value:
  abs: 0.005       # 0.5p accuracy
total_interest:
  rel: 0.001       # 0.1% relative

growth_chart:
  series:
    abs: 0.01
```

Keys not listed use the type defaults.

## Generating fixtures from sample input

The CLI has a helper:

```bash
uv run pixie validate my-tool --update-fixtures --yes
```

This runs the tool with the validator's sample inputs and writes the
response into `reference/fixture_sample.json`. Useful as a starting
point, but you should hand-author fixtures that exercise meaningful
inputs (edge cases, known answers from your spec, regression cases for
old bugs).

## Running only the reference check

```bash
uv run pixie validate my-tool --reference-only
uv run pixie validate my-tool --fixture reference/fixture_basic.json
uv run pixie validate my-tool --tag regression       # if your fixtures have tags
```

`--reference-only` skips checks 1–11 entirely, useful in CI when you've
already confirmed the contract elsewhere.

## When fixtures fail

The report includes per-output diffs:

```text
[fail] reference_fixtures_match — fixture_basic.json
   final_value:        expected 16470.09, got 16470.085 (abs diff 0.005)  ✓ within tolerance
   total_interest:     expected 6470.09,  got 6469.50   (abs diff 0.59)   ✗ exceeds 0.005
```

The skill [`debug-tool`](/Pixie/skills/diagnostics/#debug-tool) reads this
and walks back to the most likely cause.

## When NOT to add fixtures

- For stochastic tools (Monte Carlo with random seed elsewhere, LLM
  wrappers without `temperature=0`) — fixtures will flap and undermine
  confidence in the suite.
- For tools that depend on external state (a tool that hits a live API
  whose response changes hourly) — pin the seed/mock the API, or skip.
- For tools that produce intentionally large outputs (gigabyte images,
  hours of audio). Sample a small fixture instead.

Reference fixtures are a **regression safety net**, not a correctness
proof. Use them for the cases where "the answer should be X" is
unambiguous.
