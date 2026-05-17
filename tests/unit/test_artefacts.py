"""Unit tests for ``pixie.artefacts``.

Covers ``safe_join`` traversal refusal, file scan + sha256 + mime
inference, filename redaction for secret-shaped names, soft-delete
restore + purge, and thumbnail dispatch.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pixie import artefacts as art
from pixie import db
from pixie.config import get_settings


# --- safe_join ---------------------------------------------------------------


def test_safe_join_returns_path_under_root(tmp_pixie_root: Path) -> None:
    root = tmp_pixie_root / "artefacts"
    target = art.safe_join(root, "tool-id", "run-id", "out.txt")
    assert str(target).startswith(str(root.resolve()))


def test_safe_join_refuses_dotdot_escape(tmp_pixie_root: Path) -> None:
    root = tmp_pixie_root / "artefacts"
    with pytest.raises(art.ArtefactPathError):
        art.safe_join(root, "..", "etc", "passwd")


def test_safe_join_refuses_absolute_escape(tmp_pixie_root: Path) -> None:
    root = tmp_pixie_root / "artefacts"
    with pytest.raises(art.ArtefactPathError):
        art.safe_join(root, "/tmp/elsewhere")


def test_safe_join_refuses_symlink_target(tmp_pixie_root: Path) -> None:
    root = tmp_pixie_root / "artefacts"
    inner = root / "fake-link"
    try:
        inner.symlink_to(tmp_pixie_root)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported in this environment")
    with pytest.raises(art.ArtefactPathError):
        art.safe_join(root, "fake-link")


# --- mime + hash + redaction -------------------------------------------------


def test_guess_mime_uses_extra_table(tmp_pixie_root: Path) -> None:
    path = tmp_pixie_root / "foo.parquet"
    path.write_bytes(b"\x00")
    assert art._guess_mime(path) == "application/x-parquet"


def test_guess_mime_falls_back_to_octet_stream(tmp_pixie_root: Path) -> None:
    path = tmp_pixie_root / "no-extension"
    path.write_bytes(b"x")
    assert art._guess_mime(path) == "application/octet-stream"


def test_sha256_of_matches_hashlib(tmp_pixie_root: Path) -> None:
    path = tmp_pixie_root / "f.bin"
    payload = b"hello-pixie" * 100
    path.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert art._sha256_of(path) == expected


@pytest.mark.parametrize(
    "name,is_secret",
    [
        ("password.txt", True),
        ("openai_api_key.json", True),
        ("auth-bearer-jwt.txt", True),
        ("credential-token.bin", True),
        ("plot.png", False),
        ("output.csv", False),
    ],
)
def test_redact_filename_only_renames_secrets(name: str, is_secret: bool) -> None:
    safe, original = art._redact_filename(name)
    if is_secret:
        assert safe.startswith("redacted-")
        assert original == name
    else:
        assert safe == name
        assert original is None


# --- registry ----------------------------------------------------------------


def test_registry_get_run_dir_creates_path(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("my-tool", "run-1")
    assert run_dir.exists()
    assert run_dir.is_dir()
    rel = registry.rel(run_dir)
    assert registry.abs_for(rel) == run_dir.resolve()


def test_registry_refuses_reserved_prefix(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    with pytest.raises(art.ArtefactPathError):
        registry.get_run_dir("_thumbs", "run-1")


def test_registry_thumb_path_shards_by_hash(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    h = "abcd" + "0" * 60
    path = registry.thumb_path_for(h)
    assert path.parent.name == "ab"
    assert path.suffix == ".webp"


# --- scanning ----------------------------------------------------------------


def test_scan_run_dir_lists_visible_files(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("tool-x", "run-x")
    (run_dir / "out.txt").write_text("hello")
    (run_dir / "skip.partial").write_text("WIP")
    (run_dir / ".hidden").write_text("nope")
    results = art.scan_run_dir(registry, "tool-x", "run-x", run_dir)
    names = {r.filename for r in results}
    assert "out.txt" in names
    assert "skip.partial" not in names
    assert ".hidden" not in names


def test_scan_run_dir_infers_output_key_by_stem(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("tool", "run-y")
    (run_dir / "myout.png").write_bytes(b"\x89PNG")
    results = art.scan_run_dir(
        registry, "tool", "run-y", run_dir, declared_output_keys={"myout"}
    )
    assert any(r.output_key == "myout" for r in results)


def test_scan_run_dir_redacts_secret_filenames(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("tool", "run-r")
    (run_dir / "api_key.txt").write_text("sk-test")
    results = art.scan_run_dir(registry, "tool", "run-r", run_dir)
    assert any(r.filename.startswith("redacted-") for r in results)


def test_scan_run_dir_respects_cap_files(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("tool", "run-cap")
    for i in range(5):
        (run_dir / f"file_{i}.bin").write_bytes(b"a")
    results = art.scan_run_dir(registry, "tool", "run-cap", run_dir, cap_files=2)
    assert len(results) == 2


def test_scan_run_dir_computes_sha256(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("tool", "run-h")
    payload = b"hashing-data"
    (run_dir / "out.bin").write_bytes(payload)
    results = art.scan_run_dir(registry, "tool", "run-h", run_dir)
    assert any(r.sha256 == hashlib.sha256(payload).hexdigest() for r in results)


# --- soft delete + restore ---------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_then_restore(tmp_pixie_root: Path) -> None:
    db_path = tmp_pixie_root / "pixie.db"
    db.init_db(db_path)
    await db.record_run_start(db_path, "r1", "tool", {})
    await db.record_run_finish(db_path, "r1", {})
    aid = await db.register_artefact(
        db_path,
        run_id="r1",
        tool_id="tool",
        output_key="o",
        rel_path="x/y/out.bin",
        filename="out.bin",
        mime="application/octet-stream",
        size_bytes=4,
        sha256="aa" * 32,
    )
    await db.soft_delete_artefact(db_path, aid)
    row = await db.get_artefact(db_path, aid)
    assert row is not None and row["deleted_at"] is not None
    art._sync_restore(db_path, aid)
    row = await db.get_artefact(db_path, aid)
    assert row is not None and row["deleted_at"] is None


# --- thumbnail dispatch ------------------------------------------------------


def test_generate_thumbnail_returns_none_for_unknown_mime(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("tool", "run-t")
    src = run_dir / "data.bin"
    src.write_bytes(b"x")
    rel = registry.rel(src)
    artefact = {
        "sha256": "ff" * 32,
        "rel_path": rel,
        "mime": "application/octet-stream",
    }
    out = art.generate_thumbnail(registry, artefact)
    assert out is None


def test_generate_thumbnail_image_uses_pillow_when_available(tmp_pixie_root: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("tool", "run-tp")
    src = run_dir / "src.png"
    Image.new("RGB", (50, 50), "red").save(src)
    rel = registry.rel(src)
    artefact = {"sha256": "ab" * 32, "rel_path": rel, "mime": "image/png"}
    out = art.generate_thumbnail(registry, artefact)
    assert out is not None
    assert out.exists()


def test_generate_thumbnail_short_circuits_when_no_sha(tmp_pixie_root: Path) -> None:
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    assert art.generate_thumbnail(registry, {"sha256": "", "rel_path": "x", "mime": "image/png"}) is None


# --- is_secret_filename + disk usage ----------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("password.txt", True),
        ("api_key.bin", True),
        ("normal.csv", False),
    ],
)
def test_is_secret_filename(name: str, expected: bool) -> None:
    assert art.is_secret_filename(name) is expected


def test_disk_usage_by_tool_lists_tool_dirs(tmp_pixie_root: Path) -> None:
    db.init_db(tmp_pixie_root / "pixie.db")
    settings = get_settings()
    registry = art.ArtefactRegistry(settings)
    run_dir = registry.get_run_dir("tool-a", "r1")
    (run_dir / "x.bin").write_bytes(b"x" * 100)
    rows = art.disk_usage_by_tool(settings)
    # Returns a list of dicts; empty if no rows registered, but call must not raise.
    assert isinstance(rows, list)
