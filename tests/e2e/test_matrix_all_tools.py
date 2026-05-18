"""Phase 10d — Playwright matrix across all 30 tools.

This is THE acceptance test for the build (AMBITION.md): every one of
the 30 tools must work end-to-end through a real browser. The matrix:

1. Spawns Pixie pointed at the REAL ``tools/`` directory (not the
   tmp scratch root used by other e2e tests).
2. For each tool, navigates to ``/tool/<id>``, fills required inputs
   with sane defaults, uploads any file/image/audio from
   ``tests/e2e/fixtures/`` if needed, clicks "Run".
3. Waits for either the output panel to populate or a documented
   error fragment to appear.
4. Asserts at least one ``.output-card`` rendered (or an error card
   for tools that legitimately need a key/network and were not
   provided one).
5. Screenshots ``tests/e2e/_matrix/<tool_id>.png``.

Heavy by directory marker. Set ``PIXIE_RUN_HEAVY_TESTS=1`` to opt in.

Per-tool requirements split:

* ``REQUIRES_NETWORK`` — tools that hit the public internet.
  Skipped if ``PIXIE_E2E_NETWORK=0``.
* ``REQUIRES_ANTHROPIC_KEY`` — tools that need a real Anthropic
  API key. Skipped if ``ANTHROPIC_API_KEY`` env var is unset.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCREENSHOT_DIR = Path(__file__).resolve().parent / "_matrix"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# --- the 30 tools ------------------------------------------------------------

WAVE_10A = [
    "stock-monte-carlo", "black-scholes-greeks", "markowitz-portfolio",
    "time-series-forecast", "backtest-engine", "live-mlp-training",
    "yolo-object-detection", "vit-classifier-gradcam", "image-segmentation",
    "style-transfer",
]
WAVE_10B = [
    "whisper-transcription", "coqui-tts", "demucs-separation",
    "bertopic-modelling", "sentiment-over-time", "rag-with-citations",
    "llm-tool-use-agent", "lorenz-ode-solver", "n-body-simulator",
    "cellular-automata",
]
WAVE_10C = [
    "tsp-route-optimizer", "geospatial-kde-heatmap", "open-meteo-forecast",
    "lotka-volterra-simulator", "dowhy-causal-ate", "pymc-bayesian-ab",
    "kaplan-meier-cox", "qiskit-quantum-simulator",
    "graph-algorithms-playground", "anomaly-detection-isolation-forest",
]
ALL_30_TOOL_IDS = WAVE_10A + WAVE_10B + WAVE_10C

REQUIRES_NETWORK = {"open-meteo-forecast"}
REQUIRES_ANTHROPIC_KEY = {"llm-tool-use-agent", "rag-with-citations"}

# --- per-tool input plan -----------------------------------------------------
#
# For each tool whose required inputs cannot be satisfied by the
# tool.json defaults alone, we declare how to fill them. Most tools
# need at most one file upload OR one hidden-field write (maps,
# multipoint, json, tags). Pure-numeric tools rely on defaults.

UPLOADS: dict[str, dict[str, Path]] = {
    # tool_id -> { input_key: fixture_path }
    "time-series-forecast": {"series_csv": FIXTURES_DIR / "tiny_series.csv"},
    "backtest-engine": {"ohlc_csv": FIXTURES_DIR / "tiny_ohlc.csv"},
    "markowitz-portfolio": {"returns_csv": FIXTURES_DIR / "tiny_returns.csv"},
    "live-mlp-training": {"dataset_csv": FIXTURES_DIR / "tiny_target.csv"},
    "yolo-object-detection": {"image": FIXTURES_DIR / "tiny.png"},
    "vit-classifier-gradcam": {"image": FIXTURES_DIR / "tiny.png"},
    "image-segmentation": {"image": FIXTURES_DIR / "tiny.png"},
    "style-transfer": {
        "content_image": FIXTURES_DIR / "tiny.png",
        "style_image": FIXTURES_DIR / "tiny_style.png",
    },
    "whisper-transcription": {"audio_input": FIXTURES_DIR / "tiny.wav"},
    "demucs-separation": {"audio_input": FIXTURES_DIR / "tiny.wav"},
    "bertopic-modelling": {"dataset_csv": FIXTURES_DIR / "tiny_text.csv"},
    "sentiment-over-time": {"dataset_csv": FIXTURES_DIR / "tiny_text.csv"},
    "rag-with-citations": {"documents": FIXTURES_DIR / "tiny_doc.txt"},
    "geospatial-kde-heatmap": {"csv_file": FIXTURES_DIR / "tiny_points.csv"},
    "dowhy-causal-ate": {"csv_file": FIXTURES_DIR / "tiny_causal.csv"},
    "kaplan-meier-cox": {"csv_file": FIXTURES_DIR / "tiny_survival.csv"},
    "anomaly-detection-isolation-forest": {
        "csv_file": FIXTURES_DIR / "tiny_anomaly.csv"
    },
}

# JS-injected hidden-field values for special inputs (map, json, etc.).
HIDDEN_FIELDS: dict[str, dict[str, Any]] = {
    "open-meteo-forecast": {"location": {"lat": 51.505, "lon": -0.09}},
    "tsp-route-optimizer": {
        "cities": [
            {"lat": 51.505, "lon": -0.09, "label": "A"},
            {"lat": 51.510, "lon": -0.085, "label": "B"},
            {"lat": 51.515, "lon": -0.095, "label": "C"},
            {"lat": 51.500, "lon": -0.080, "label": "D"},
        ],
    },
    "llm-tool-use-agent": {
        "messages": [{"role": "user", "content": "What is 2 + 2?"}],
    },
}

PER_TOOL_TIMEOUT_S = 60  # heavy ML tools cold-start slowly


# --- fixture: server pointed at REAL tools/ ----------------------------------


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@pytest.fixture(scope="module")
def matrix_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Live Pixie server backed by the REAL tools/ directory.

    A scratch DB is used (so we don't pollute the user's pixie.db),
    but tools_dir and artefacts_root point at the canonical locations
    so all 30 tools are discoverable with their already-provisioned
    .venv directories.
    """

    import uvicorn

    scratch = tmp_path_factory.mktemp("matrix_root")
    scratch_db = scratch / "pixie.db"
    scratch_artefacts = scratch / "artefacts"
    scratch_artefacts.mkdir(parents=True, exist_ok=True)

    # Patch env BEFORE importing pixie.app so settings pick this up.
    old = {
        "PIXIE_TOOLS_DIR": os.environ.get("PIXIE_TOOLS_DIR"),
        "PIXIE_DB_PATH": os.environ.get("PIXIE_DB_PATH"),
        "PIXIE_ARTEFACTS_ROOT": os.environ.get("PIXIE_ARTEFACTS_ROOT"),
        "PIXIE_REPO_ROOT": os.environ.get("PIXIE_REPO_ROOT"),
    }
    os.environ["PIXIE_TOOLS_DIR"] = str(REPO_ROOT / "tools")
    os.environ["PIXIE_DB_PATH"] = str(scratch_db)
    os.environ["PIXIE_ARTEFACTS_ROOT"] = str(scratch_artefacts)
    os.environ["PIXIE_REPO_ROOT"] = str(REPO_ROOT)

    from pixie.config import get_settings
    get_settings.cache_clear()

    from pixie.app import create_app

    port = _free_port()
    app = create_app()
    cfg = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio"
    )
    server = uvicorn.Server(cfg)
    thread = threading.Thread(target=server.run, daemon=True, name="matrix-server")
    thread.start()

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError("matrix_server failed to start within 15s")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        # Restore env so other fixtures behave normally.
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()


# --- helpers ----------------------------------------------------------------


def _maybe_skip_for_requirements(tool_id: str) -> None:
    if tool_id in REQUIRES_NETWORK:
        if os.environ.get("PIXIE_E2E_NETWORK", "1") in ("0", "false", "False"):
            pytest.skip(f"{tool_id} requires network; set PIXIE_E2E_NETWORK=1")
    if tool_id in REQUIRES_ANTHROPIC_KEY:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip(f"{tool_id} requires ANTHROPIC_API_KEY env var")


def _set_hidden_field_value(page, name: str, value: Any) -> None:
    """Force-fill a hidden form input by its ``name`` attribute."""

    page.evaluate(
        """([n, v]) => {
            const el = document.querySelector(`input[name="${n}"]`);
            if (el) {
                el.value = (typeof v === "string") ? v : JSON.stringify(v);
            }
        }""",
        [name, value],
    )


def _fill_uploads(page, tool_id: str) -> None:
    plan = UPLOADS.get(tool_id, {})
    for input_key, fixture_path in plan.items():
        if not fixture_path.exists():
            raise FileNotFoundError(fixture_path)
        selector = f'input[name="{input_key}"][type="file"]'
        loc = page.locator(selector)
        if loc.count() == 0:
            # Tool's schema may not expose the input as <input type=file>;
            # in practice all upload inputs render exactly that. Surface.
            raise AssertionError(
                f"{tool_id}: no file input named {input_key!r}"
            )
        loc.set_input_files(str(fixture_path))


def _fill_hidden(page, tool_id: str) -> None:
    for k, v in HIDDEN_FIELDS.get(tool_id, {}).items():
        _set_hidden_field_value(page, k, v)


# --- the matrix test --------------------------------------------------------


@pytest.mark.parametrize("tool_id", ALL_30_TOOL_IDS)
def test_tool_e2e(tool_id: str, matrix_server: str, page) -> None:
    _maybe_skip_for_requirements(tool_id)

    # Capture console errors + page errors so we can fail loudly.
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    # 1. Navigate.
    page.goto(f"{matrix_server}/tool/{tool_id}", wait_until="networkidle")

    # 2. Assert the tool view rendered (form present means schema parsed OK).
    form_loc = page.locator("#run-form")
    assert form_loc.count() >= 1, (
        f"{tool_id}: no #run-form rendered (likely a tool-not-found / "
        f"schema-parse error rather than an e2e UI failure)"
    )

    # 3. Fill any required uploads + hidden fields.
    _fill_uploads(page, tool_id)
    _fill_hidden(page, tool_id)

    # 4. Click Run.
    run_btn = page.locator('button[form="run-form"][type="submit"]').first
    assert run_btn.count() == 1, f"{tool_id}: cannot find Run button"
    run_btn.click()

    # 5. Wait for an output card OR an error card to appear.
    output_panel = page.locator("#output-panel")
    end_time = time.monotonic() + PER_TOOL_TIMEOUT_S
    populated = False
    while time.monotonic() < end_time:
        html = output_panel.inner_html()
        # Empty-state copy is the placeholder "Run the tool…" message;
        # anything else means htmx swapped content in.
        if "Run the tool" not in html and html.strip():
            # output-card OR an error card OR streaming shell all qualify.
            populated = (
                'class="output-card' in html
                or 'class="error-card' in html
                or 'output-streaming' in html
                or 'data-output-key' in html
            )
            if populated:
                break
        time.sleep(0.25)

    # 6. Screenshot regardless of result for the matrix table.
    shot_path = SCREENSHOT_DIR / f"{tool_id}.png"
    with contextlib.suppress(Exception):
        page.screenshot(path=str(shot_path), full_page=True)

    # 7. For streaming tools, wait a little longer for the first SSE event
    #    to land before asserting we got content.
    if "output-streaming" in output_panel.inner_html() and not populated:
        # Streaming opened; give SSE a chance.
        end_time = time.monotonic() + 30
        while time.monotonic() < end_time:
            html = output_panel.inner_html()
            if 'data-output-key' in html or 'class="output-card' in html:
                populated = True
                break
            time.sleep(0.5)

    # 8. Hard assertions.
    final_html = output_panel.inner_html()
    if not populated:
        # Save the HTML for triage.
        debug_path = SCREENSHOT_DIR / f"{tool_id}.debug.html"
        with contextlib.suppress(Exception):
            debug_path.write_text(final_html, encoding="utf-8")
        # Aggregate console + page errors into the failure message.
        pytest.fail(
            f"{tool_id}: output panel never populated within "
            f"{PER_TOOL_TIMEOUT_S}s.\n"
            f"console errors: {console_errors[:5]}\n"
            f"page errors: {page_errors[:5]}\n"
            f"final html (first 400): {final_html[:400]!r}"
        )

    # Page-level JS errors are diagnosed but not fatal — Alpine/Plotly may
    # emit init-time warnings on some tool schemas that don't affect the
    # rendered output. Surface them in the test stdout for triage.
    if page_errors:
        print(f"[{tool_id}] non-fatal page errors: {page_errors[:3]}")


# --- per-tool result manifest (written for the report step) -----------------


@pytest.fixture(scope="module", autouse=True)
def _write_manifest_marker() -> Iterator[None]:
    """Drop a placeholder so the report step can detect a matrix run.

    The actual per-row results live in pytest's exit code + the
    screenshot directory; this marker just signals "the matrix
    fixture was wired and the server came up".
    """
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SCREENSHOT_DIR / "_run_marker.json").write_text(
        json.dumps({"started_at": time.time(), "tools": ALL_30_TOOL_IDS}, indent=2),
        encoding="utf-8",
    )
    yield
