"""Additional artefact registry coverage: registration, lifecycle, watchdog."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

from pixie import artefacts as art
from pixie import db
from pixie.artefacts import (
    ArtefactPathError,
    ArtefactRegistry,
    RunArtefactsContext,
    disk_usage_by_tool,
    generate_thumbnail,
    hard_delete,
    is_secret_filename,
    purge_expired,
    quota_watchdog,
    register_run_artefacts,
    rehydrate_outputs,
    restore,
    scan_run_dir,
    soft_delete,
    sweeper_once,
)
from pixie.config import get_settings


@pytest.fixture
def registry(tmp_pixie_root: Path, monkeypatch: pytest.MonkeyPatch) -> ArtefactRegistry:
    # Pin artefacts_root to the scratch tree so we don't write into the
    # real repo's artefacts/ directory.
    monkeypatch.setenv("PIXIE_ARTEFACTS_ROOT", str(tmp_pixie_root / "artefacts"))
    get_settings.cache_clear()
    settings = get_settings()
    return ArtefactRegistry(settings)


@pytest.fixture
def init_db(tmp_pixie_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PIXIE_ARTEFACTS_ROOT", str(tmp_pixie_root / "artefacts"))
    get_settings.cache_clear()
    settings = get_settings()
    db.init_db(settings.db_path)
    return settings.db_path


async def _make_run(db_path: Path, run_id: str, tool_id: str) -> None:
    """Insert a parent run row so artefact FK is satisfied."""

    await db.record_run_start(db_path, run_id, tool_id, {"x": 1})


# --- registration ----------------------------------------------------------


@pytest.mark.asyncio
async def test_register_run_artefacts_round_trips(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    await _make_run(init_db, "run1", "toolA")
    run_dir = registry.get_run_dir("toolA", "run1")
    (run_dir / "result.txt").write_text("hello")
    new_ids = await register_run_artefacts(
        registry, "toolA", "run1", run_dir=run_dir,
    )
    assert len(new_ids) == 1
    rows = await db.list_artefacts(init_db, run_id="run1")
    assert len(rows) == 1
    assert rows[0]["filename"] == "result.txt"


@pytest.mark.asyncio
async def test_register_run_artefacts_idempotent(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    await _make_run(init_db, "run2", "toolA")
    run_dir = registry.get_run_dir("toolA", "run2")
    (run_dir / "result.txt").write_text("hello")
    first = await register_run_artefacts(registry, "toolA", "run2", run_dir=run_dir)
    second = await register_run_artefacts(registry, "toolA", "run2", run_dir=run_dir)
    assert first
    assert second == []


@pytest.mark.asyncio
async def test_register_run_artefacts_no_files(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    run_dir = registry.get_run_dir("toolA", "run3")
    new_ids = await register_run_artefacts(registry, "toolA", "run3", run_dir=run_dir)
    assert new_ids == []


@pytest.mark.asyncio
async def test_register_run_artefacts_with_declared_keys(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    await _make_run(init_db, "run4", "toolA")
    run_dir = registry.get_run_dir("toolA", "run4")
    (run_dir / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    new_ids = await register_run_artefacts(
        registry, "toolA", "run4", run_dir=run_dir,
        declared_output_keys={"chart"},
    )
    assert new_ids
    rows = await db.list_artefacts(init_db, run_id="run4")
    assert rows[0]["output_key"] == "chart"


# --- scan partials + dotfiles --------------------------------------------


def test_scan_run_dir_ignores_partials(
    registry: ArtefactRegistry,
) -> None:
    run_dir = registry.get_run_dir("toolB", "run-partial")
    (run_dir / "real.txt").write_text("x")
    (run_dir / "stream.txt.partial").write_text("partial")
    (run_dir / ".hidden").write_text("h")
    out = scan_run_dir(registry, "toolB", "run-partial", run_dir)
    names = [s.filename for s in out]
    assert "real.txt" in names
    assert "stream.txt.partial" not in names
    assert ".hidden" not in names


def test_scan_run_dir_handles_subdirs_for_output_keys(
    registry: ArtefactRegistry,
) -> None:
    run_dir = registry.get_run_dir("toolB", "run-sub")
    sub = run_dir / "gallery"
    sub.mkdir()
    (sub / "001.png").write_bytes(b"\x89PNG")
    (sub / "002.png").write_bytes(b"\x89PNG")
    out = scan_run_dir(
        registry, "toolB", "run-sub", run_dir,
        declared_output_keys={"gallery"},
    )
    assert all(s.output_key == "gallery" for s in out)


# --- soft delete / restore / purge ---------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_then_restore_round_trip(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    await _make_run(init_db, "run1", "toolC")
    run_dir = registry.get_run_dir("toolC", "run1")
    (run_dir / "x.txt").write_text("x")
    ids = await register_run_artefacts(registry, "toolC", "run1", run_dir=run_dir)
    settings = registry.settings
    await soft_delete(settings, ids[0])
    rows = await db.list_artefacts(init_db, run_id="run1")
    assert rows == []
    await restore(settings, ids[0])
    rows = await db.list_artefacts(init_db, run_id="run1")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_purge_expired_no_op_when_nothing_old(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    purged = await purge_expired(registry, days=0)
    assert purged == 0


@pytest.mark.asyncio
async def test_hard_delete_unknown_returns_false(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    out = await hard_delete(registry, 999999)
    assert out is False


@pytest.mark.asyncio
async def test_hard_delete_removes_row_and_file(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    await _make_run(init_db, "run1", "toolD")
    run_dir = registry.get_run_dir("toolD", "run1")
    f = run_dir / "x.bin"
    f.write_bytes(b"\x00")
    ids = await register_run_artefacts(registry, "toolD", "run1", run_dir=run_dir)
    out = await hard_delete(registry, ids[0])
    assert out is True
    rows = await db.list_artefacts(init_db, run_id="run1", include_deleted=True)
    assert rows == []
    assert not f.exists()


# --- rehydrate -----------------------------------------------------------


def test_rehydrate_outputs_no_input_returns_empty() -> None:
    assert rehydrate_outputs(None, {}) == {}


def test_rehydrate_outputs_unchanged_when_no_outputs_key() -> None:
    inputs = {"foo": "bar"}
    assert rehydrate_outputs(inputs, {}) == inputs


def test_rehydrate_outputs_swaps_handle_with_row() -> None:
    payload = {"outputs": {"chart": {"_artefact_id": 7}}}
    rows = {"chart": {"id": 7, "filename": "x.png", "mime": "image/png", "size_bytes": 10}}
    out = rehydrate_outputs(payload, rows)
    assert out["outputs"]["chart"]["filename"] == "x.png"


def test_rehydrate_outputs_wraps_scalar_into_handle() -> None:
    payload = {"outputs": {"y": 42}}
    rows = {"y": {"id": 9, "filename": "y.json",
                   "mime": "application/json", "size_bytes": 4}}
    out = rehydrate_outputs(payload, rows)
    assert out["outputs"]["y"]["_artefact_id"] == 9
    assert out["outputs"]["y"]["value"] == 42


# --- quota watchdog ------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_watchdog_triggers_on_overflow(
    registry: ArtefactRegistry, tmp_pixie_root: Path,
) -> None:
    run_dir = registry.get_run_dir("toolE", "run1")
    big = run_dir / "huge.bin"
    big.write_bytes(b"\x00" * 4096)
    ctx = RunArtefactsContext(
        run_id="run1", tool_id="toolE", artefacts_dir=run_dir,
    )
    called: list[str] = []

    def on_exceeded(c):
        called.append(c.run_id)

    task = asyncio.create_task(
        quota_watchdog(ctx, max_bytes=10, on_exceeded=on_exceeded, interval_s=0.05),
    )
    await asyncio.wait_for(task, timeout=2.0)
    assert ctx.killed_for_quota is True
    assert called == ["run1"]


@pytest.mark.asyncio
async def test_quota_watchdog_cancellable(
    registry: ArtefactRegistry,
) -> None:
    run_dir = registry.get_run_dir("toolE", "run-cancel")
    ctx = RunArtefactsContext(
        run_id="run-cancel", tool_id="toolE", artefacts_dir=run_dir,
    )
    task = asyncio.create_task(
        quota_watchdog(ctx, max_bytes=1_000_000, interval_s=10.0),
    )
    await asyncio.sleep(0.05)
    task.cancel()
    # Should not raise
    await asyncio.gather(task, return_exceptions=True)
    assert ctx.killed_for_quota is False


# --- sweeper -------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweeper_once_returns_counts(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    counts = await sweeper_once(registry)
    assert "runs_pruned" in counts
    assert "artefacts_hard_deleted" in counts
    assert "partials_removed" in counts


@pytest.mark.asyncio
async def test_sweeper_removes_old_partials(
    registry: ArtefactRegistry, init_db: Path,
) -> None:
    run_dir = registry.get_run_dir("toolF", "run-partial")
    p = run_dir / "stream.txt.partial"
    p.write_text("x")
    # Make it look ancient.
    ancient = time.time() - 7200
    import os
    os.utime(p, (ancient, ancient))
    counts = await sweeper_once(registry)
    assert counts["partials_removed"] >= 1


# --- thumbnails ----------------------------------------------------------


def test_generate_thumbnail_for_real_image(
    registry: ArtefactRegistry,
) -> None:
    from PIL import Image
    run_dir = registry.get_run_dir("toolG", "run1")
    src = run_dir / "im.png"
    Image.new("RGB", (32, 32), (100, 50, 200)).save(src)
    rel = registry.rel(src)
    artefact = {
        "sha256": "abc12300" + "0" * 56,  # plausible-shape
        "rel_path": rel,
        "mime": "image/png",
    }
    out = generate_thumbnail(registry, artefact)
    assert out is not None
    assert out.exists()


def test_generate_thumbnail_returns_cached(
    registry: ArtefactRegistry,
) -> None:
    from PIL import Image
    run_dir = registry.get_run_dir("toolG", "run-cache")
    src = run_dir / "im.png"
    Image.new("RGB", (16, 16), (0, 0, 0)).save(src)
    rel = registry.rel(src)
    artefact = {"sha256": "x" * 64, "rel_path": rel, "mime": "image/png"}
    first = generate_thumbnail(registry, artefact)
    second = generate_thumbnail(registry, artefact)
    assert first == second


def test_generate_thumbnail_missing_source_returns_none(
    registry: ArtefactRegistry,
) -> None:
    artefact = {
        "sha256": "y" * 64, "rel_path": "no/such/file.png", "mime": "image/png",
    }
    assert generate_thumbnail(registry, artefact) is None


# --- helpers / utilities ------------------------------------------------


def test_is_secret_filename_positive() -> None:
    assert is_secret_filename("api_key.txt") is True
    assert is_secret_filename("password.bin") is True


def test_is_secret_filename_negative() -> None:
    assert is_secret_filename("result.csv") is False


def test_disk_usage_by_tool_empty(init_db: Path) -> None:
    settings = get_settings()
    assert disk_usage_by_tool(settings) == []
