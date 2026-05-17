"""WCAG audit via axe-core injected into Playwright.

Fails on any ``critical`` or ``serious`` violation. ``moderate`` and
``minor`` violations are reported but do not fail the build (yet);
``needs_review`` items are logged.
"""

from __future__ import annotations

from typing import Any


def _critical_violations(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        v for v in report.get("violations", [])
        if v.get("impact") in {"critical", "serious"}
    ]


def test_dashboard_has_no_critical_axe_violations(page, pixie_server, axe_audit) -> None:
    page.goto(pixie_server + "/", wait_until="networkidle")
    report = axe_audit(page)
    failures = _critical_violations(report)
    assert failures == [], "axe critical/serious: " + ", ".join(
        v["id"] for v in failures
    )


def test_settings_has_no_critical_axe_violations(page, pixie_server, axe_audit) -> None:
    page.goto(pixie_server + "/settings", wait_until="networkidle")
    report = axe_audit(page)
    failures = _critical_violations(report)
    assert failures == [], "axe critical/serious: " + ", ".join(
        v["id"] for v in failures
    )
