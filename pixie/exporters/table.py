"""table exporter -- csv, tsv, json, md, html, xlsx, parquet."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from pixie.exporters import (
    ExporterError,
    ExporterMissingDependency,
    register_exporter,
)
from pixie.exporters._common import coerce_value, csv_scalar, json_default, html_shell


def _rows_and_columns(raw: Any, spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Accept BOTH ``{columns, rows}`` and ``list[dict]`` shapes.

    - ``{"columns": [...], "rows": [...]}`` — explicit columns list.
      ``columns`` may be either a list of strings (header keys) or a list
      of column-spec dicts (``{"key": ..., "label": ...}``). When ``rows``
      is a list of lists, they're zipped to dicts using the columns.
    - ``{"rows": [{...}, ...]}`` — rows-only dict.
    - ``list[dict]`` — bare list of row dicts.
    """

    value = coerce_value(raw)
    rows: list[dict[str, Any]] = []
    inline_columns: list[str] | None = None

    if isinstance(value, dict):
        raw_rows = value.get("rows")
        raw_cols = value.get("columns")
        if isinstance(raw_cols, list) and raw_cols:
            if all(isinstance(c, dict) for c in raw_cols):
                inline_columns = [
                    str(c.get("key") or c.get("label") or "")
                    for c in raw_cols
                ]
            else:
                inline_columns = [str(c) for c in raw_cols]
            inline_columns = [c for c in inline_columns if c]
        if isinstance(raw_rows, list):
            for r in raw_rows:
                if isinstance(r, dict):
                    rows.append(r)
                elif isinstance(r, (list, tuple)) and inline_columns:
                    rows.append({
                        inline_columns[i]: v
                        for i, v in enumerate(r)
                        if i < len(inline_columns)
                    })
    elif isinstance(value, list):
        for r in value:
            if isinstance(r, dict):
                rows.append(r)

    columns_spec = spec.get("columns") if isinstance(spec, dict) else None
    if columns_spec:
        columns = [
            c.get("key") for c in columns_spec
            if isinstance(c, dict) and c.get("key")
        ]
    elif inline_columns:
        columns = inline_columns
    elif rows:
        columns = list(rows[0].keys())
    else:
        columns = []
    return rows, columns


def table_to_csv(raw, *, prov, output_key, spec, opts, **_) -> tuple[bytes, str]:
    rows, columns = _rows_and_columns(raw, spec)
    delim = "\t" if (opts or {}).get("delimiter") == "tab" else ","
    buf = io.StringIO()
    buf.write(f"# {prov}\n")
    writer = csv.DictWriter(
        buf, fieldnames=columns, extrasaction="ignore",
        delimiter=delim, quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({h: csv_scalar(row.get(h)) for h in columns})
    ext = "tsv" if delim == "\t" else "csv"
    return buf.getvalue().encode("utf-8"), f"{output_key}.{ext}"


def table_to_tsv(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    return table_to_csv(raw, prov=prov, output_key=output_key, spec=spec, opts={"delimiter": "tab"})


def table_to_json(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    rows, columns = _rows_and_columns(raw, spec)
    payload = {"columns": columns, "rows": rows, "_pixie_provenance": prov}
    return (
        json.dumps(payload, indent=2, default=json_default).encode("utf-8"),
        f"{output_key}.json",
    )


def table_to_md(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    rows, columns = _rows_and_columns(raw, spec)
    if not columns:
        return f"<!-- {prov} -->\n\n_no rows_\n".encode("utf-8"), f"{output_key}.md"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [header, sep]
    truncated = 0
    limit = 1000
    for idx, row in enumerate(rows):
        if idx >= limit:
            truncated = len(rows) - limit
            break
        cells = []
        for col in columns:
            cell = csv_scalar(row.get(col)).replace("|", "\\|").replace("\n", " ")
            cells.append(cell)
        body.append("| " + " | ".join(cells) + " |")
    if truncated:
        body.append(f"\n_+{truncated} more rows_")
    payload = f"<!-- {prov} -->\n\n" + "\n".join(body) + "\n"
    return payload.encode("utf-8"), f"{output_key}.md"


def table_to_html(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    rows, columns = _rows_and_columns(raw, spec)
    from html import escape
    body = [f"<h1>{escape(output_key)}</h1>", "<table>", "<thead><tr>"]
    for col in columns:
        body.append(f"<th>{escape(str(col))}</th>")
    body.append("</tr></thead><tbody>")
    for row in rows:
        body.append("<tr>")
        for col in columns:
            body.append(f"<td>{escape(csv_scalar(row.get(col)))}</td>")
        body.append("</tr>")
    body.append("</tbody></table>")
    return html_shell("".join(body), prov, pre=False).encode("utf-8"), f"{output_key}.html"


def table_to_xlsx(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    try:
        from openpyxl import Workbook  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "openpyxl is required for .xlsx export",
            hint="run `uv add openpyxl`",
        ) from exc
    rows, columns = _rows_and_columns(raw, spec)
    wb = Workbook()
    ws = wb.active
    ws.title = "data"[:31]
    if columns:
        ws.append(columns)
    for row in rows:
        ws.append([_xlsx_scalar(row.get(c)) for c in columns])
    meta = wb.create_sheet("_meta")
    meta["A1"] = "pixie_provenance"
    meta["B1"] = prov
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"{output_key}.xlsx"


def _xlsx_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool, str)):
        return value
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False, default=json_default)
    return str(value)


def table_to_parquet(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    try:
        import pyarrow as pa  # type: ignore[import-not-found]
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "pyarrow is required for .parquet export",
            hint="run `uv add pyarrow`",
        ) from exc
    rows, _ = _rows_and_columns(raw, spec)
    table = pa.Table.from_pylist(rows) if rows else pa.table({})
    metadata = dict(table.schema.metadata or {})
    metadata[b"pixie_provenance"] = prov.encode("utf-8")
    table = table.replace_schema_metadata(metadata)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue(), f"{output_key}.parquet"


register_exporter("table", "csv", table_to_csv, default=True)
register_exporter("table", "tsv", table_to_tsv)
register_exporter("table", "json", table_to_json)
register_exporter("table", "md", table_to_md)
register_exporter("table", "html", table_to_html)
register_exporter("table", "xlsx", table_to_xlsx)
register_exporter("table", "parquet", table_to_parquet)
