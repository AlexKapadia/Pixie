# reference-tool fixtures

Two fixtures exercise the `reference_fixtures_match` validator check
(check #12):

- `fixture_basic.json` — sqrt(4) = 2.0 exactly; covers `text_exact` for
  the summary string and `numeric_isclose` for the result.
- `fixture_tolerance.json` — sqrt(2) ≈ 1.41 to 2dp; covers the
  per-fixture `tolerance.result.rtol = 1e-2` override.
