"""Accessibility helpers.

Loads the official ``axe.min.js`` source into a Playwright page via
``page.add_script_tag(content=...)`` and evaluates ``axe.run()`` to get
a violations report. Asserting on the result is the test's job; the
helper is just plumbing.

The axe-core source is downloaded on first use into
``tests/a11y/.axe-cache/axe.min.js``. CI may pre-populate this if
network access is restricted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

AXE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
AXE_CACHE_DIR = Path(__file__).resolve().parent / ".axe-cache"
AXE_CACHE_PATH = AXE_CACHE_DIR / "axe.min.js"


def _ensure_axe_source() -> str:
    """Return the axe-core JS source, downloading on first use."""

    if AXE_CACHE_PATH.exists():
        return AXE_CACHE_PATH.read_text(encoding="utf-8")
    AXE_CACHE_DIR.mkdir(exist_ok=True)
    try:
        import urllib.request

        with urllib.request.urlopen(AXE_CDN_URL, timeout=10) as response:
            data = response.read().decode("utf-8")
    except Exception as exc:
        pytest.skip(f"could not fetch axe-core ({exc}) - pre-populate {AXE_CACHE_PATH}")
    AXE_CACHE_PATH.write_text(data, encoding="utf-8")
    return data


@pytest.fixture
def axe_audit() -> Callable[..., dict]:
    """Return ``axe_audit(page) -> {violations: [...]}``.

    The default test only asserts no ``critical`` or ``serious`` issues.
    """

    axe_source = _ensure_axe_source()

    def _audit(page) -> dict:
        page.add_script_tag(content=axe_source)
        result_json = page.evaluate(
            "() => axe.run().then(r => JSON.stringify(r))"
        )
        return json.loads(result_json)

    return _audit
