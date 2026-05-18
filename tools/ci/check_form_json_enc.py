"""Settings-form HTMX json-enc audit.

HTMX defaults to JSON-encoding form payloads when the ``json-enc``
extension is loaded globally. Pixie's settings endpoints expect
``application/x-www-form-urlencoded`` (FastAPI's ``Form(...)`` parser
does not understand JSON). Forms that POST to ``/settings/...`` MUST
therefore opt OUT of the json-enc extension AND explicitly declare
``application/x-www-form-urlencoded`` so the contract is visible in
the markup.

This audit walks every ``pixie/templates/**/*.html`` file, locates each
``<form>`` tag, and — if it targets a settings endpoint (via ``hx-post``
or ``action``) — asserts both attributes are present. Exits 1 with the
list of violating file:line pairs on failure.

Used by ``.github/workflows/ci.yml``; safe to run locally:

    python tools/ci/check_form_json_enc.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_ROOT = ROOT / "pixie" / "templates"

FORM_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE | re.DOTALL)
HX_POST_RE = re.compile(r"""hx-post\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
ACTION_RE = re.compile(r"""\baction\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
HX_EXT_RE = re.compile(r"""hx-ext\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
HX_ENCODING_RE = re.compile(r"""hx-encoding\s*=\s*["']([^"']*)["']""", re.IGNORECASE)

REQUIRED_EXT_TOKEN = "ignore:json-enc"
REQUIRED_ENCODING = "application/x-www-form-urlencoded"


def _targets_settings(form_tag: str) -> str | None:
    """Return the endpoint URL if this form posts to /settings/, else None."""
    for pattern in (HX_POST_RE, ACTION_RE):
        m = pattern.search(form_tag)
        if m and "/settings/" in m.group(1):
            return m.group(1)
    return None


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def main() -> int:
    if not TEMPLATES_ROOT.exists():
        print(f"no templates dir at {TEMPLATES_ROOT.relative_to(ROOT)}; nothing to check.")
        return 0

    violations: list[str] = []
    for html in sorted(TEMPLATES_ROOT.glob("**/*.html")):
        try:
            text = html.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(f"{html.relative_to(ROOT)}: unreadable ({exc})")
            continue

        for form_match in FORM_RE.finditer(text):
            form_tag = form_match.group(0)
            target = _targets_settings(form_tag)
            if not target:
                continue

            line = _line_of(text, form_match.start())
            problems: list[str] = []

            ext_match = HX_EXT_RE.search(form_tag)
            ext_value = ext_match.group(1) if ext_match else ""
            # ``hx-ext`` may carry multiple comma-separated tokens.
            ext_tokens = {tok.strip() for tok in ext_value.split(",") if tok.strip()}
            if REQUIRED_EXT_TOKEN not in ext_tokens:
                problems.append(f'missing hx-ext="{REQUIRED_EXT_TOKEN}"')

            enc_match = HX_ENCODING_RE.search(form_tag)
            enc_value = (enc_match.group(1).strip().lower() if enc_match else "")
            if enc_value != REQUIRED_ENCODING:
                problems.append(f'missing hx-encoding="{REQUIRED_ENCODING}"')

            if problems:
                violations.append(
                    f"{html.relative_to(ROOT)}:{line}: "
                    f"form -> {target}: {'; '.join(problems)}"
                )

    if violations:
        print("\n".join(violations))
        print(f"\n{len(violations)} form(s) need the json-enc opt-out.", file=sys.stderr)
        return 1

    print("All settings forms opt out of json-enc.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
