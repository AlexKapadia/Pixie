"""number, boolean, kv exporters."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from pixie.exporters import ExporterError, register_exporter
from pixie.exporters._common import coerce_value, csv_scalar, json_default


# --- number ------------------------------------------------------------------


def _format_number(value: Any, fmt: str | None, precision: int | None, unit: str | None) -> str:
    if value is None:
        return ""
    fmt = fmt or "decimal"
    if precision is None:
        precision = 2 if fmt == "currency" else None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if fmt == "percent":
        rendered = f"{v * 100:.{precision or 2}f}%"
    elif fmt == "currency":
        rendered = f"£{v:,.{precision or 2}f}"
    elif fmt == "scientific":
        rendered = f"{v:.{precision or 3}e}"
    else:
        rendered = f"{v:.{precision}f}" if precision is not None else str(v)
    if unit and fmt not in {"currency", "percent"}:
        rendered = f"{rendered} {unit}"
    return rendered


def number_to_txt(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    value = coerce_value(raw)
    rendered = _format_number(
        value, spec.get("format"), spec.get("precision"), spec.get("unit"),
    )
    return f"# {prov}\n{output_key}: {rendered}\n".encode("utf-8"), f"{output_key}.txt"


def number_to_json(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    value = coerce_value(raw)
    payload: dict[str, Any] = {
        output_key: value if not isinstance(value, float) or value == value else None,
        "_format": spec.get("format") or "decimal",
        "_unit": spec.get("unit"),
        "_pixie_provenance": prov,
    }
    return (
        json.dumps(payload, indent=2, default=json_default).encode("utf-8"),
        f"{output_key}.json",
    )


def number_to_csv(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    value = coerce_value(raw)
    buf = io.StringIO()
    buf.write(f"# {prov}\n")
    writer = csv.writer(buf)
    writer.writerow([output_key])
    writer.writerow([csv_scalar(value)])
    return buf.getvalue().encode("utf-8"), f"{output_key}.csv"


register_exporter("number", "txt", number_to_txt, default=True)
register_exporter("number", "json", number_to_json)
register_exporter("number", "csv", number_to_csv)


# --- boolean -----------------------------------------------------------------


def boolean_to_txt(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    value = coerce_value(raw)
    if value is None:
        raise ExporterError(f"boolean output {output_key!r} has no value")
    truthy = bool(value)
    label = (spec.get("true_label") if truthy else spec.get("false_label"))
    rendered = label or ("true" if truthy else "false")
    return f"# {prov}\n{rendered}\n".encode("utf-8"), f"{output_key}.txt"


def boolean_to_json(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    value = coerce_value(raw)
    payload = {output_key: bool(value), "_pixie_provenance": prov}
    return (
        json.dumps(payload, indent=2).encode("utf-8"),
        f"{output_key}.json",
    )


register_exporter("boolean", "txt", boolean_to_txt, default=True)
register_exporter("boolean", "json", boolean_to_json)


# --- kv ----------------------------------------------------------------------


def _kv_dict(raw: Any) -> dict[str, Any]:
    value = coerce_value(raw)
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        # Some tools emit [{key, value}, ...].
        out: dict[str, Any] = {}
        for entry in value:
            if isinstance(entry, dict) and "key" in entry and "value" in entry:
                out[str(entry["key"])] = entry["value"]
        return out
    return {}


def kv_to_json(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    payload = dict(_kv_dict(raw))
    payload["_pixie_provenance"] = prov
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_default).encode("utf-8"),
        f"{output_key}.json",
    )


def kv_to_csv(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    data = _kv_dict(raw)
    buf = io.StringIO()
    buf.write(f"# {prov}\n")
    writer = csv.writer(buf)
    writer.writerow(["key", "value"])
    for k, v in data.items():
        writer.writerow([k, csv_scalar(v)])
    return buf.getvalue().encode("utf-8"), f"{output_key}.csv"


def kv_to_yaml(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    data = _kv_dict(raw)
    lines = [f"# {prov}"]
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            lines.append(f"{k}: {json.dumps(v, default=json_default)}")
        elif isinstance(v, str):
            escaped = v.replace('"', '\\"')
            lines.append(f'{k}: "{escaped}"')
        else:
            lines.append(f"{k}: {v}")
    body = "\n".join(lines) + "\n"
    return body.encode("utf-8"), f"{output_key}.yaml"


def kv_to_toml(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    data = _kv_dict(raw)
    lines = [f"# {prov}"]
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            raise ExporterError(
                f"kv with nested values incompatible with TOML for key {k!r}",
                hint="export as JSON or YAML instead",
            )
        if isinstance(v, str):
            escaped = v.replace('"', '\\"')
            lines.append(f'{k} = "{escaped}"')
        elif isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        else:
            lines.append(f"{k} = {v}")
    return ("\n".join(lines) + "\n").encode("utf-8"), f"{output_key}.toml"


def kv_to_md(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    data = _kv_dict(raw)
    rows = [f"<!-- {prov} -->", "", "| key | value |", "| --- | --- |"]
    for k, v in data.items():
        cell = csv_scalar(v).replace("|", "\\|")
        rows.append(f"| {k} | {cell} |")
    return ("\n".join(rows) + "\n").encode("utf-8"), f"{output_key}.md"


register_exporter("kv", "json", kv_to_json, default=True)
register_exporter("kv", "csv", kv_to_csv)
register_exporter("kv", "yaml", kv_to_yaml)
register_exporter("kv", "toml", kv_to_toml)
register_exporter("kv", "md", kv_to_md)


# --- progress (snapshot) -----------------------------------------------------


def progress_to_json(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    value = coerce_value(raw)
    payload = {"progress": value, "_pixie_provenance": prov}
    return json.dumps(payload, indent=2).encode("utf-8"), f"{output_key}.json"


def progress_to_txt(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    value = coerce_value(raw)
    return f"# {prov}\nprogress: {value}\n".encode("utf-8"), f"{output_key}.txt"


register_exporter("progress", "json", progress_to_json, default=True)
register_exporter("progress", "txt", progress_to_txt)
