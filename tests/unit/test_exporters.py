"""Unit tests for ``pixie.exporters``.

Covers the dispatcher (every (type, default_format) pair), provenance
footer presence, ``safe_filename`` sanitisation, the per-module scalar
+ structured + text exporters, and the registry's negative paths
(unsupported format, missing exporter).
"""

from __future__ import annotations

import json

import pytest

from pixie import exporters
from pixie.exporters import (
    ExporterUnsupported,
    default_format,
    make_provenance,
    safe_filename,
    supported_formats,
    supports,
)


# --- registry surface --------------------------------------------------------


# Every (output_type, default_format) the registry knows about. Tracks
# the matrix declared by per-type modules.
TYPES_AND_DEFAULTS = [
    ("number", "txt"),
    ("boolean", "txt"),
    ("kv", "json"),
    ("progress", "json"),
    ("text", "txt"),
    ("stream_text", "txt"),
    ("log", "txt"),
    ("markdown", "md"),
    ("code", "source"),
    ("latex", "tex"),
    ("diff", "patch"),
    ("table", "csv"),
    ("tree", "json"),
    ("timeline", "json"),
    ("gantt", "csv"),
]


@pytest.mark.parametrize("output_type,fmt", TYPES_AND_DEFAULTS)
def test_default_format_matches_registry(output_type: str, fmt: str) -> None:
    assert default_format(output_type) == fmt
    assert supports(output_type, fmt) is True


@pytest.mark.parametrize("output_type,fmt", TYPES_AND_DEFAULTS)
def test_supported_formats_includes_default(output_type: str, fmt: str) -> None:
    assert fmt in supported_formats(output_type)


def test_default_format_unknown_raises() -> None:
    with pytest.raises(exporters.ExporterUnsupported):
        default_format("no-such-type")


def test_supports_returns_false_for_unknown_pair() -> None:
    assert supports("text", "no-such-format") is False
    assert supports("no-such-type", "txt") is False


# --- provenance --------------------------------------------------------------


def test_make_provenance_includes_all_components() -> None:
    p = make_provenance(tool_id="t", run_id="r", output_key="o")
    assert "Exported from Pixie" in p
    assert "tool=t" in p
    assert "run=r" in p
    assert "output=o" in p
    assert "ts=" in p


def test_make_provenance_omits_none_pieces() -> None:
    p = make_provenance(tool_id=None, run_id=None, output_key=None)
    assert "tool=" not in p
    assert "run=" not in p
    assert "output=" not in p
    assert "ts=" in p


# --- safe_filename -----------------------------------------------------------


@pytest.mark.parametrize(
    "hint,fmt,bad_chars",
    [
        ("../../etc/passwd", "txt", ("/", "\\")),
        ("name with spaces", "json", (" ",)),
        ("evil:name*?", "csv", (":", "*", "?")),
    ],
)
def test_safe_filename_strips_path_separators(hint, fmt, bad_chars) -> None:
    out = safe_filename(hint, "k", fmt)
    for ch in bad_chars:
        assert ch not in out
    assert out.endswith(f".{fmt}")


def test_safe_filename_handles_windows_reserved() -> None:
    out = safe_filename("CON", "out", "txt")
    assert not out.lower().startswith("con.")


def test_safe_filename_truncates_long_basenames() -> None:
    huge = "a" * 500
    out = safe_filename(huge, "k", "txt")
    assert len(out) <= 244


def test_safe_filename_falls_back_to_output_key() -> None:
    out = safe_filename(None, "myout", "txt")
    assert out.startswith("myout")
    assert out.endswith(".txt")


# --- dispatcher --------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_dispatches_to_number() -> None:
    payload, name = await exporters.export(42, "number", output_key="x")
    assert name == "x.txt"
    assert b"Exported from Pixie" in payload
    assert b"x: 42" in payload


@pytest.mark.asyncio
async def test_export_rejects_unsupported_format() -> None:
    with pytest.raises(ExporterUnsupported):
        await exporters.export(42, "number", format="docx")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output_type,value,fmt",
    [
        ("number", 3.14, None),
        ("boolean", True, None),
        ("kv", {"a": 1, "b": 2}, None),
        ("progress", 0.5, None),
        ("text", "hello world", None),
        ("text", "another", "json"),
        ("markdown", "# Title", None),
        ("code", "print(1)", None),
        ("table", {"columns": ["a"], "rows": [{"a": 1}]}, None),
        ("table", {"columns": ["a"], "rows": [{"a": 1}]}, "json"),
        ("tree", {"label": "root", "children": []}, None),
        ("timeline", [{"label": "x", "at": "2026-01-01"}], None),
        ("log", "line 1\nline 2", None),
        ("kv", {"a": 1}, "yaml"),
        ("kv", {"a": 1}, "md"),
        ("kv", {"a": 1}, "toml"),
    ],
)
async def test_export_per_type_produces_bytes_with_provenance(
    output_type: str, value, fmt
) -> None:
    payload, name = await exporters.export(
        value, output_type, format=fmt, output_key="o", tool_id="t", run_id="r"
    )
    assert isinstance(payload, bytes)
    assert len(payload) > 0
    assert isinstance(name, str)
    # All text-shaped exporters embed the provenance string in the body
    # (HTML/PDF/binary exporters embed it as a comment or footer).
    if not name.endswith((".pdf", ".png", ".xlsx", ".parquet", ".html", ".docx", ".webp")):
        text = payload.decode("utf-8", errors="replace")
        assert "Exported from Pixie" in text


# --- per-module sanity (scalar) ---------------------------------------------


@pytest.mark.asyncio
async def test_number_to_json_round_trips() -> None:
    payload, _ = await exporters.export(99, "number", format="json", output_key="n")
    obj = json.loads(payload.decode("utf-8"))
    assert obj["n"] == 99
    assert obj["_pixie_provenance"]


@pytest.mark.asyncio
async def test_boolean_uses_label_when_provided() -> None:
    payload, _ = await exporters.export(
        True, "boolean", output_key="b", spec={"true_label": "YES"}
    )
    assert b"YES" in payload


@pytest.mark.asyncio
async def test_kv_csv_emits_key_value_rows() -> None:
    payload, _ = await exporters.export(
        {"alpha": 1, "beta": 2}, "kv", format="csv", output_key="kv"
    )
    text = payload.decode("utf-8")
    assert "alpha" in text and "beta" in text
    assert "key,value" in text


@pytest.mark.asyncio
async def test_kv_toml_refuses_nested_values() -> None:
    with pytest.raises(exporters.ExporterError):
        await exporters.export(
            {"a": {"nested": 1}}, "kv", format="toml", output_key="kv"
        )


# --- per-module sanity (text family) ----------------------------------------


@pytest.mark.asyncio
async def test_text_to_html_escapes_html_payload() -> None:
    payload, _ = await exporters.export(
        "<script>alert(1)</script>", "text", format="html", output_key="msg"
    )
    text = payload.decode("utf-8")
    # The script tag must NOT appear executable in body content; it should be
    # entity-encoded (single or double encoded both prove escaping happened).
    assert "<script>alert(1)</script>" not in text
    assert "script" in text  # the literal word survives, just escaped


@pytest.mark.asyncio
async def test_markdown_md_wraps_provenance() -> None:
    payload, _ = await exporters.export("# Hi", "markdown", output_key="m")
    text = payload.decode("utf-8")
    assert text.lstrip().startswith("<!--") or "Exported from Pixie" in text


@pytest.mark.asyncio
async def test_log_to_jsonl_one_object_per_line() -> None:
    log_value = "INFO foo\nWARN bar\nERROR baz"
    payload, _ = await exporters.export(
        log_value, "log", format="jsonl", output_key="l"
    )
    text = payload.decode("utf-8").strip()
    lines = [ln for ln in text.split("\n") if not ln.startswith("#")]
    for line in lines:
        json.loads(line)


# --- per-module sanity (table + tree) ---------------------------------------


@pytest.mark.asyncio
async def test_table_to_csv_emits_header_and_rows() -> None:
    value = {"columns": [{"key": "a"}, {"key": "b"}], "rows": [{"a": 1, "b": 2}]}
    payload, name = await exporters.export(value, "table", format="csv", output_key="t")
    text = payload.decode("utf-8")
    assert name.endswith(".csv")
    assert "a,b" in text
    assert "1,2" in text


@pytest.mark.asyncio
async def test_table_to_md_renders_table_syntax() -> None:
    value = {"columns": [{"key": "a"}], "rows": [{"a": 1}, {"a": 2}]}
    payload, _ = await exporters.export(value, "table", format="md", output_key="t")
    text = payload.decode("utf-8")
    assert "| a |" in text
    assert "| --- |" in text


@pytest.mark.asyncio
async def test_tree_to_md_renders_bullet_outline() -> None:
    value = {"label": "root", "children": [{"label": "child", "children": []}]}
    payload, _ = await exporters.export(value, "tree", format="md", output_key="t")
    text = payload.decode("utf-8")
    assert "- root" in text
    assert "- child" in text


# --- registry-level negatives ------------------------------------------------


def test_supported_formats_unknown_raises() -> None:
    with pytest.raises(ExporterUnsupported):
        supported_formats("no-such-type")
