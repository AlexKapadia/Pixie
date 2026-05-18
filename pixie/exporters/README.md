# Pixie exporters

One output type, many formats. Each exporter module registers itself with the
dispatcher (`pixie.exporters.register_exporter`); routes call `export(...)`.

## Chart PNG fallback (kaleido)

`charts._to_static` produces PNG / SVG / PDF via Plotly + `kaleido`. When
`kaleido` is missing (or its Chromium bootstrap fails), the exporter falls
back to interactive **HTML** and raises `ExporterDegraded(actual_format="html")`.

The `/api/runs/{run_id}/outputs/{output_key}/export` and
`/api/artefacts/{artefact_id}/export` routes catch this, return 200 with the
HTML payload, and set `X-Pixie-Export-Degraded: html` on the response so the
caller can warn the user.

Install `kaleido` to restore native PNG/SVG/PDF: `uv add kaleido==0.2.1`.
