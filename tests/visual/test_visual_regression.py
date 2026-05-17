"""Visual-regression sweep against design artboards.

Each test points Playwright at a Pixie page and asserts the resulting
screenshot is within the pixel-diff threshold (default 2%). First run
writes the baseline and skips; subsequent runs compare.

Wave 2 (Phase 6e visual agent) expands this list to cover every page
listed in DESIGN_SPEC.md.
"""

from __future__ import annotations


def test_dashboard_visual(page, pixie_server, compare_screenshot) -> None:
    page.goto(pixie_server + "/", wait_until="networkidle")
    compare_screenshot(page, "dashboard_empty")


def test_settings_visual(page, pixie_server, compare_screenshot) -> None:
    page.goto(pixie_server + "/settings", wait_until="networkidle")
    compare_screenshot(page, "settings_default")
