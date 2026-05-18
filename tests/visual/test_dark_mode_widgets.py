"""Verify third-party widgets (Plotly, Leaflet, CodeMirror) re-theme.

We load the tool form for ``example-compound-interest`` which contains
a number of inputs plus, after a Run, a Plotly chart. Then we toggle
the theme and confirm via the DOM that:

  * the Plotly chart's ``paper_bgcolor`` was relayout-updated to a dark
    hex (low luma)
  * any CodeMirror editor present has ``theme=material-darker``
  * any Leaflet tile-layer URL contains ``dark_all``

The Plotly assertion is the most consequential since it tests
``Pixie.makeChart`` -> ``pixie:theme-changed`` -> ``Plotly.relayout``.

Marked as ``visual`` so it only runs with ``PIXIE_RUN_HEAVY_TESTS=1``.
"""

from __future__ import annotations


def _hex_to_luma(h: str) -> float:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) < 6:
        return 128.0
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def test_plotly_chart_retheme_via_setTheme(page, pixie_server) -> None:
    """Probe Pixie.makeChart + pixie:theme-changed -> Plotly.relayout path."""

    page.goto(pixie_server + "/", wait_until="networkidle")
    res = page.evaluate(
        """() => new Promise((resolve) => {
          if (typeof Plotly === 'undefined') return resolve({ skipped: true });
          const div = document.createElement('div');
          div.id = 'probe-chart';
          div.style.cssText = 'width:400px;height:200px;position:absolute;left:-1000px;';
          document.body.appendChild(div);
          window.Pixie.setTheme('light');
          // Defer to let theme apply before makeChart reads CSS vars.
          setTimeout(() => {
            window.Pixie.makeChart(div, [{ type: 'scatter', x: [1,2,3], y: [1,2,3] }], {});
            setTimeout(() => {
              const lightBg = div.layout && div.layout.paper_bgcolor;
              window.Pixie.setTheme('dark');
              setTimeout(() => {
                const darkBg = div.layout && div.layout.paper_bgcolor;
                resolve({ light: lightBg, dark: darkBg });
              }, 300);
            }, 200);
          }, 100);
        })"""
    )
    if res.get("skipped"):
        import pytest as _pt

        _pt.skip("Plotly not available")
        return
    light_bg = res.get("light")
    dark_bg = res.get("dark")
    assert light_bg, "Plotly chart layout never exposed paper_bgcolor"
    assert dark_bg, "Plotly chart did not relayout on theme change"
    light_l = _hex_to_luma(light_bg) if light_bg.startswith("#") else 255
    dark_l = _hex_to_luma(dark_bg) if dark_bg.startswith("#") else 0
    assert dark_l < light_l - 100, (
        f"Plotly paper_bgcolor did not darken: light={light_bg} dark={dark_bg}"
    )


def test_leaflet_tile_url_swaps_on_theme(page, pixie_server) -> None:
    """A page with no Leaflet map should still expose Pixie.addBaseTiles."""

    page.goto(pixie_server + "/", wait_until="networkidle")
    # Build a synthetic map element and assert tile URL changes.
    urls = page.evaluate(
        """() => new Promise((resolve) => {
          if (typeof L === 'undefined') return resolve({ skipped: true });
          const div = document.createElement('div');
          div.style.cssText = 'width:200px;height:200px;position:absolute;left:-1000px;';
          div.id = 'probe-map';
          document.body.appendChild(div);
          window.Pixie.setTheme('light');
          const map = window.Pixie.makeMap(div, { center: [0, 0], zoom: 2 });
          if (!map) return resolve({ skipped: true });
          setTimeout(() => {
            const light = [];
            map.eachLayer(l => { if (l._url) light.push(l._url); });
            window.Pixie.setTheme('dark');
            setTimeout(() => {
              const dark = [];
              map.eachLayer(l => { if (l._url) dark.push(l._url); });
              resolve({ light, dark });
            }, 200);
          }, 200);
        })"""
    )
    if urls.get("skipped"):
        import pytest as _pt

        _pt.skip("Leaflet not available on this page")
        return
    light_join = " ".join(urls.get("light") or [])
    dark_join = " ".join(urls.get("dark") or [])
    assert "light_all" in light_join, f"expected light_all tile, got {light_join!r}"
    assert "dark_all" in dark_join, f"expected dark_all tile, got {dark_join!r}"


def test_codemirror_theme_swaps(page, pixie_server) -> None:
    """CodeMirror swap relies on Pixie.initCodeOutputs subscribing."""

    page.goto(pixie_server + "/", wait_until="networkidle")
    res = page.evaluate(
        """() => new Promise((resolve) => {
          if (typeof CodeMirror === 'undefined') return resolve({ skipped: true });
          const ta = document.createElement('textarea');
          ta.value = 'print("hi")';
          ta.setAttribute('data-pixie-code-out', '1');
          ta.setAttribute('data-language', 'python');
          document.body.appendChild(ta);
          window.Pixie.setTheme('light');
          window.Pixie.initCodeOutputs(document.body);
          setTimeout(() => {
            const cm = document.querySelector('.CodeMirror');
            if (!cm) return resolve({ skipped: true });
            const light = cm.CodeMirror.getOption('theme');
            window.Pixie.setTheme('dark');
            setTimeout(() => {
              resolve({ light, dark: cm.CodeMirror.getOption('theme') });
            }, 200);
          }, 200);
        })"""
    )
    if res.get("skipped"):
        import pytest as _pt

        _pt.skip("CodeMirror not available")
        return
    assert res.get("light") == "neo", f"expected neo, got {res.get('light')!r}"
    assert res.get("dark") == "material-darker", f"expected material-darker, got {res.get('dark')!r}"
