# Scaffold templates

Each subdirectory is a starter Pixie tool: `tool.json`, `pyproject.toml`,
`main.py`, plus an optional `src/{{PACKAGE}}/` package. The
`add-tool-from-*` skills copy one of these, substitute `{{TOOL_ID}}` /
`{{TOOL_NAME}}` / `{{PACKAGE}}` / `{{DESCRIPTION}}`, then run the
validator.

## Inputs contract

Every scaffold builds its `Inputs` pydantic model dynamically from
`tool.json` at import time (see `_build_inputs_model` in each template's
`main.py` or `handlers.py`). Each input becomes a field whose Python
type is derived from its JSON-schema `type`, and whose default is the
`default` value from the schema (or `None` for genuinely optional
inputs). `RunRequest.inputs` is typed as `dict[str, Any]` over the wire,
then `Inputs.model_validate(request.inputs)` is called server-side so
that a `null` sent by the dashboard for a key with a schema default
resolves to that default. The user's compute function uses attribute
access (`typed_inputs.series`) and never has to defend against `None`
for any keyed default.
