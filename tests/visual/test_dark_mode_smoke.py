"""Dark-mode parity smoke test.

For every key page in Pixie, load it light, screenshot it, toggle theme
to dark via ``Pixie.setTheme('dark')``, wait for the transition, and
screenshot again. Then compare mean brightness of the two screenshots —
the dark variant must be substantially darker than the light one, or
the screen has orphan styles that don't follow the theme.

Marked as ``visual`` so it only runs with ``PIXIE_RUN_HEAVY_TESTS=1``.
"""

from __future__ import annotations

from io import BytesIO

import pytest

# Per-page minimum mean-brightness delta (light - dark) on the 0..255 scale.
# Some pages have a lot of chrome (sidebars, headers); empty pages have less
# painted area so the delta is smaller. 20/255 ≈ 8% is a safe floor for any
# real screen that re-themes — orphan styles tend to leave the delta < 5.
MIN_BRIGHTNESS_DELTA = 20.0

PAGES = [
    ("/", "dashboard"),
    ("/library", "library"),
    ("/tools", "tools_grid"),
    ("/settings", "settings"),
]


def _mean_brightness(png_bytes: bytes) -> float:
    """Return mean luma (0..255) over the PNG."""

    from PIL import Image

    img = Image.open(BytesIO(png_bytes)).convert("L")  # 8-bit grayscale
    # Image.histogram returns 256 bin counts.
    hist = img.histogram()
    total = sum(hist)
    if total == 0:
        return 0.0
    weighted = sum(i * count for i, count in enumerate(hist))
    return weighted / total


@pytest.mark.parametrize(("path", "name"), PAGES)
def test_theme_switch_darkens_page(page, pixie_server, path, name) -> None:
    url = pixie_server + path
    page.goto(url, wait_until="networkidle")
    # Ensure we start in light.
    page.evaluate("window.Pixie && Pixie.setTheme('light')")
    page.wait_for_timeout(200)
    light_shot = page.screenshot(full_page=True)
    light_mean = _mean_brightness(light_shot)

    page.evaluate("window.Pixie && Pixie.setTheme('dark')")
    # Allow transition + theme-changed-driven re-paints.
    page.wait_for_timeout(400)
    dark_shot = page.screenshot(full_page=True)
    dark_mean = _mean_brightness(dark_shot)

    delta = light_mean - dark_mean
    assert delta >= MIN_BRIGHTNESS_DELTA, (
        f"{name!r} ({path}) did not darken: "
        f"light={light_mean:.1f} dark={dark_mean:.1f} delta={delta:.1f} "
        f"(min={MIN_BRIGHTNESS_DELTA})"
    )


def test_theme_event_dispatched(page, pixie_server) -> None:
    """Pixie.setTheme must dispatch ``pixie:theme-changed`` on document."""

    page.goto(pixie_server + "/", wait_until="networkidle")
    received = page.evaluate(
        """
        () => new Promise((resolve) => {
          let got = null;
          document.addEventListener('pixie:theme-changed', (e) => {
            got = (e && e.detail && e.detail.theme) || null;
            resolve(got);
          }, { once: true });
          window.Pixie.setTheme('dark');
          setTimeout(() => resolve(got), 500);
        })
        """
    )
    assert received == "dark", f"expected 'dark', got {received!r}"
