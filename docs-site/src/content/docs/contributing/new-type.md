---
title: Adding a new input/output type
description: The whole workflow for shipping a new renderer type.
sidebar:
  order: 4
---

The most common Pixie contribution. The renderer is intentionally
boring — adding a new type is four files.

## Workflow

import { Steps } from "@astrojs/starlight/components";

<Steps>

1. **Add the Pydantic class** in `pixie/discovery.py`. Inherit from
   `_InputBase` or the appropriate output base.

   ```python
   class FrequencyInput(_InputBase):
       type: Literal["frequency"]
       min_hz: float = 20.0
       max_hz: float = 20000.0
       step: float = 1.0
       unit: str = "Hz"
   ```

   Add it to the discriminated union:

   ```python
   InputSpec = Annotated[
       Union[
           TextInput, NumberInput, ...,
           FrequencyInput,
       ],
       Field(discriminator="type"),
   ]
   ```

2. **Add the partial.** For an input,
   `pixie/templates/partials/inputs/frequency.html`:

   ```jinja
   {%- from "partials/inputs/_macros.html" import field_open, field_close -%}
   {{ field_open(spec, field_id) }}
     <div class="input-row" x-data='{ value: {{ initial_json }} }'>
       <input type="range"
              id="{{ field_id }}"
              name="{{ spec.key }}"
              min="{{ spec.min_hz }}"
              max="{{ spec.max_hz }}"
              step="{{ spec.step }}"
              x-model.number="value"
              class="range" />
       <output class="t-meta" x-text="value + ' {{ spec.unit }}'"></output>
     </div>
   {{ field_close(spec) }}
   ```

   For an output, follow the shape of an existing
   `templates/partials/outputs/<type>.html` and use the `output_card`
   macro.

3. **Add the dispatch entry** so the renderer knows about the new type.
   In `pixie/renderer/inputs.py` (or `outputs.py`):

   ```python
   PARTIAL["frequency"] = "inputs/frequency.html"
   ```

   For outputs that need a required value shape (most non-scalar
   outputs), also add to `_OUTPUT_OBJECT_REQUIREMENTS` in
   `pixie/validator.py`:

   ```python
   _OUTPUT_OBJECT_REQUIREMENTS["spectrogram"] = ("data", "sample_rate")
   ```

4. **Add a sample-input rule** so the validator can synthesise a value
   when no `default` is given. In `pixie/validator.py`:

   ```python
   _INPUT_DEFAULTS["frequency"] = lambda spec: (spec.min_hz + spec.max_hz) / 2
   ```

5. **Add a test fixture** under `tests/fixtures/types/` containing a
   minimal tool that exercises the new type, then a test in
   `tests/unit/test_renderer_inputs.py` (or outputs).

</Steps>

That's the whole workflow. The renderer is decoupled enough that you
should never need to touch the existing types when adding a new one.

## Naming conventions

- Input/output type names are **snake_case** (`map_polygon`,
  `chart_scatter`).
- Keep them short and concrete (`frequency`, not `audio_frequency_picker`).
- If the type would naturally pair with a sibling, name it accordingly
  (`chart_line` / `chart_area`, `map_points` / `map_heatmap`).

## When NOT to add a type

- **One-off needs.** If only one tool would use it, add a `json` input
  with a `schema` and let the tool parse — don't bloat the renderer.
- **Tiny variations.** A "small text" vs "big text" distinction is a
  CSS class, not a type.
- **Validation logic.** `number` with `min`/`max` is fine. Don't add a
  `positive_number` type.
- **Display tweaks on outputs.** `format` and `precision` on `number`
  exist for a reason. Use them.

The 25 input types and 39 output types we have today cover ~99% of
imaginable tools. Adding a new one should require a clear story for at
least two tools that need it.

## After you add a type

- Update [Input types](/Pixie/build/inputs/) or [Output types](/Pixie/build/outputs/)
  in the docs site (this repo).
- If you added a chart type, update the docs' `pixie.js` mention of
  Plotly in [Concepts → Schema-driven UI](/Pixie/concepts/renderer/).
- Mention it in the PR description as "new type: ...". Reviewers will
  look for the four-file pattern above.
