# Contributing to Pixie

Thanks for your interest in Pixie. Issues and PRs are welcome.

Full contributor docs live on the docs site:

- **Overview** — https://alexkapadia.github.io/Pixie/contributing/overview/
- **Dev setup** — https://alexkapadia.github.io/Pixie/contributing/dev-setup/
- **Adding a new output type** — https://alexkapadia.github.io/Pixie/contributing/new-type/
- **Style** — https://alexkapadia.github.io/Pixie/contributing/style/
- **Tests** — https://alexkapadia.github.io/Pixie/contributing/tests/
- **Out of scope** — https://alexkapadia.github.io/Pixie/contributing/out-of-scope/

## TL;DR

1. Fork and clone, then `uv sync` and `pixie dev` (see Dev setup).
2. Make your change on a branch.
3. Run the validator on any tool you touch — if it passes, it's probably in.
4. Open a PR against `main`. Keep the diff focused; one concern per PR.

## What not to commit

- `artefacts/`, `pixie.db`, `tools/*/.venv`, `tools/*/data`, `tools/*/models`, `.env` — runtime state, not source.
- Bundled tools — `tools/` is local-only on `main`; ships empty.

## Reporting bugs

Open an issue at https://github.com/AlexKapadia/Pixie/issues with steps to reproduce, expected vs actual, and platform/Python version.

## Licence

By contributing, you agree your contributions are licensed under the MIT Licence.
