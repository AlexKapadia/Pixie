"""File comparator: sha256 or mime-dispatched (pdf/csv/json)."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from typing import Any

from pixie.comparators._base import Diff
from pixie.comparators.table import compare_table


_pdfplumber = None
_PDF_DEGRADED: str | None = None


def _ensure_pdfplumber() -> str | None:
    global _pdfplumber, _PDF_DEGRADED
    if _PDF_DEGRADED is not None:
        return _PDF_DEGRADED
    if _pdfplumber is not None:
        return None
    try:
        import pdfplumber  # noqa: F401
    except ImportError as exc:
        _PDF_DEGRADED = (
            f"degraded: {exc.name} not installed; "
            "pip install pixie[accuracy] for PDF text comparison"
        )
        return _PDF_DEGRADED
    import pdfplumber
    _pdfplumber = pdfplumber
    return None


def _file_bytes(value: Any) -> tuple[bytes, str]:
    """Return (bytes, mime). Inspects ``data`` / ``data_url`` / inline base64."""

    if isinstance(value, str):
        if value.startswith("data:") and "," in value:
            prefix, b64 = value.split(",", 1)
            mime = prefix[5:].split(";", 1)[0]
            try:
                return base64.b64decode(b64), mime
            except (ValueError, TypeError):
                return value.encode("utf-8"), "text/plain"
        return value.encode("utf-8"), "text/plain"

    if not isinstance(value, dict):
        return repr(value).encode("utf-8"), "application/octet-stream"

    mime = str(value.get("mime") or value.get("content_type") or "application/octet-stream")
    raw = value.get("data") or value.get("data_url") or value.get("content")
    if raw is None:
        return b"", mime
    if isinstance(raw, bytes):
        return raw, mime
    if isinstance(raw, str):
        if raw.startswith("data:") and "," in raw:
            prefix, b64 = raw.split(",", 1)
            mime = prefix[5:].split(";", 1)[0] or mime
            try:
                return base64.b64decode(b64), mime
            except (ValueError, TypeError):
                return raw.encode("utf-8"), mime
        try:
            return base64.b64decode(raw), mime
        except (ValueError, TypeError):
            return raw.encode("utf-8"), mime
    return repr(raw).encode("utf-8"), mime


def compare_file(
    output_key: str,
    output_type: str,
    expected: Any,
    actual: Any,
    tolerance: dict[str, Any],
) -> Diff | None:
    """Compare two file outputs."""

    mode = tolerance.get("compare", "mime_dispatch")
    if mode == "skip":
        return None

    e_bytes, e_mime = _file_bytes(expected)
    a_bytes, a_mime = _file_bytes(actual)

    if mode == "sha256":
        return _compare_sha256(output_key, output_type, e_bytes, a_bytes)

    # mime_dispatch
    if e_mime == a_mime == "application/pdf":
        reason = _ensure_pdfplumber()
        if reason is None:
            return _compare_pdf(output_key, output_type, e_bytes, a_bytes)
        diff = _compare_sha256(output_key, output_type, e_bytes, a_bytes)
        if diff is not None:
            diff.metric = (diff.metric or "") + f" [{reason}]"
        return diff
    if e_mime == a_mime == "application/json":
        try:
            e_obj = json.loads(e_bytes.decode("utf-8"))
            a_obj = json.loads(a_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return Diff(
                output_key=output_key, output_type=output_type, comparator="file_json",
                expected=e_bytes[:120], actual=a_bytes[:120],
                metric=f"json parse failure: {exc}",
            )
        if e_obj == a_obj:
            return None
        return Diff(
            output_key=output_key, output_type=output_type, comparator="file_json",
            expected=e_obj, actual=a_obj, metric="json content differs",
        )
    if e_mime == a_mime == "text/csv":
        return _compare_csv(output_key, output_type, e_bytes, a_bytes, tolerance)

    return _compare_sha256(output_key, output_type, e_bytes, a_bytes)


def _compare_sha256(
    output_key: str, output_type: str, e_bytes: bytes, a_bytes: bytes,
) -> Diff | None:
    e_hash = hashlib.sha256(e_bytes).hexdigest()
    a_hash = hashlib.sha256(a_bytes).hexdigest()
    if e_hash == a_hash and len(e_bytes) == len(a_bytes):
        return None
    return Diff(
        output_key=output_key, output_type=output_type, comparator="sha256_or_mime",
        expected=f"sha256={e_hash[:12]}", actual=f"sha256={a_hash[:12]}",
        metric=(
            f"sha256 differs: {e_hash[:8]}... vs {a_hash[:8]}... "
            f"(size {len(e_bytes)} vs {len(a_bytes)})"
        ),
    )


def _compare_pdf(
    output_key: str, output_type: str, e_bytes: bytes, a_bytes: bytes,
) -> Diff | None:
    try:
        with _pdfplumber.open(io.BytesIO(e_bytes)) as pdf:
            e_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        with _pdfplumber.open(io.BytesIO(a_bytes)) as pdf:
            a_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:
        return Diff(
            output_key=output_key, output_type=output_type, comparator="file_pdf_text",
            expected=None, actual=None,
            metric=f"pdf text extract failed: {exc}",
        )
    if e_text.strip() == a_text.strip():
        return None
    return Diff(
        output_key=output_key, output_type=output_type, comparator="file_pdf_text",
        expected=e_text[:200], actual=a_text[:200],
        metric=f"pdf text differs ({len(e_text)} vs {len(a_text)} chars)",
    )


def _compare_csv(
    output_key: str, output_type: str,
    e_bytes: bytes, a_bytes: bytes, tolerance: dict[str, Any],
) -> Diff | None:
    e_rows = list(csv.reader(io.StringIO(e_bytes.decode("utf-8", errors="replace"))))
    a_rows = list(csv.reader(io.StringIO(a_bytes.decode("utf-8", errors="replace"))))
    if not e_rows or not a_rows:
        return _compare_sha256(output_key, output_type, e_bytes, a_bytes)
    e_columns = e_rows[0]
    a_columns = a_rows[0]
    e_payload = {"columns": e_columns, "rows": e_rows[1:]}
    a_payload = {"columns": a_columns, "rows": a_rows[1:]}
    csv_tolerance = {
        "compare": "rows_unordered",
        "float_rtol": float(tolerance.get("float_rtol", 1.0e-6)),
        "float_atol": float(tolerance.get("float_atol", 1.0e-9)),
    }
    diff = compare_table(output_key, output_type, e_payload, a_payload, csv_tolerance)
    if diff is None:
        return None
    diff.comparator = "file_csv_table"
    return diff
