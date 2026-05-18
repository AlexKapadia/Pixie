"""Visual-regression helpers.

Uses Playwright's sync API (``page`` fixture from the top-level
conftest) plus a Pillow-based pixel diff. ``pixelmatch-py`` is
unmaintained as of 2026; the small helper below is sufficient at the
1% / 2% diff thresholds we target.

Baselines live at ``tests/visual/baselines/<name>.png``. On first run
(or when ``PIXIE_VISUAL_UPDATE_BASELINE=1`` is set) the helper writes
the screenshot as the new baseline and the test passes.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

BASELINES = Path(__file__).resolve().parent / "baselines"
DEFAULT_DIFF_THRESHOLD = 0.02  # 2% of pixels may differ


def _pixel_diff(baseline_path: Path, candidate_bytes: bytes) -> float:
    """Return the fraction of pixels that differ between two PNGs.

    Both images must be the same size; if they aren't the test should
    rebaseline. Returns a value in [0, 1].
    """

    from io import BytesIO

    from PIL import Image, ImageChops

    baseline = Image.open(baseline_path).convert("RGB")
    candidate = Image.open(BytesIO(candidate_bytes)).convert("RGB")
    if baseline.size != candidate.size:
        return 1.0
    diff = ImageChops.difference(baseline, candidate)
    bbox = diff.getbbox()
    if bbox is None:
        return 0.0
    # Count non-zero pixels in the diff (any channel changed).
    histogram = diff.crop(bbox).histogram()
    # Sum bins 1..255 across the three channels; bin 0 is "no change".
    diff_pixels = sum(histogram[1:256]) + sum(histogram[257:512]) + sum(histogram[513:768])
    total_pixels = baseline.size[0] * baseline.size[1] * 3
    return min(1.0, diff_pixels / total_pixels)


@pytest.fixture
def compare_screenshot() -> Callable[..., None]:
    """Take a screenshot and assert it matches the on-disk baseline.

    Usage::

        def test_dashboard(page, pixie_server, compare_screenshot):
            page.goto(pixie_server + "/")
            compare_screenshot(page, "dashboard")
    """

    BASELINES.mkdir(exist_ok=True)
    update_baseline = os.environ.get(
        "PIXIE_VISUAL_UPDATE_BASELINE", ""
    ) not in ("", "0", "false", "False")

    def _compare(page, name: str, *, threshold: float = DEFAULT_DIFF_THRESHOLD) -> None:
        baseline_path = BASELINES / f"{name}.png"
        shot = page.screenshot(full_page=True)
        if not baseline_path.exists() or update_baseline:
            baseline_path.write_bytes(shot)
            pytest.skip(
                f"baseline {name!r} written - re-run to verify"
            )
        diff = _pixel_diff(baseline_path, shot)
        assert diff <= threshold, (
            f"visual diff for {name!r} = {diff:.2%} exceeds {threshold:.2%}"
        )

    return _compare
