"""tree, timeline, gantt exporters."""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

from pixie.exporters import register_exporter
from pixie.exporters._common import coerce_value, csv_scalar, json_default


# --- tree --------------------------------------------------------------------


def _tree_value(raw: Any) -> dict[str, Any]:
    value = coerce_value(raw)
    if isinstance(value, dict):
        return value
    return {"label": str(value), "children": []}


def tree_to_json(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    payload = {"tree": _tree_value(raw), "_pixie_provenance": prov}
    return (
        json.dumps(payload, indent=2, default=json_default).encode("utf-8"),
        f"{output_key}.json",
    )


def tree_to_yaml(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    def dump(node, depth):
        lines = [f"{'  ' * depth}- label: {json.dumps(node.get('label', ''))}"]
        for child in node.get("children") or []:
            lines.append(f"{'  ' * (depth + 1)}children:")
            lines.extend(dump(child, depth + 2))
        return lines
    body = [f"# {prov}"] + dump(_tree_value(raw), 0)
    return ("\n".join(body) + "\n").encode("utf-8"), f"{output_key}.yaml"


def tree_to_md(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    lines = [f"<!-- {prov} -->", ""]

    def walk(node, depth):
        lines.append(f"{'  ' * depth}- {node.get('label', '')}")
        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(_tree_value(raw), 0)
    return ("\n".join(lines) + "\n").encode("utf-8"), f"{output_key}.md"


register_exporter("tree", "json", tree_to_json, default=True)
register_exporter("tree", "yaml", tree_to_yaml)
register_exporter("tree", "md", tree_to_md)


# --- timeline ----------------------------------------------------------------


def _timeline_events(raw: Any) -> list[dict[str, Any]]:
    value = coerce_value(raw)
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and "events" in value:
        return list(value.get("events") or [])
    return []


def timeline_to_json(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    payload = {"events": _timeline_events(raw), "_pixie_provenance": prov}
    return (
        json.dumps(payload, indent=2, default=json_default).encode("utf-8"),
        f"{output_key}.json",
    )


def timeline_to_csv(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    events = _timeline_events(raw)
    buf = io.StringIO()
    buf.write(f"# {prov}\n")
    writer = csv.writer(buf)
    writer.writerow(["t", "label", "category"])
    for event in events:
        writer.writerow([
            csv_scalar(event.get("t")),
            csv_scalar(event.get("label")),
            csv_scalar(event.get("category")),
        ])
    return buf.getvalue().encode("utf-8"), f"{output_key}.csv"


def _ical_escape(value: str) -> str:
    return (value or "").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _ical_dt(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%dT%H%M%SZ")
    return str(value or "").replace("-", "").replace(":", "").split(".")[0] + "Z"


def timeline_to_ical(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    events = _timeline_events(raw)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Pixie//EN",
              f"X-PIXIE-PROVENANCE:{_ical_escape(prov)}"]
    for event in events:
        uid = str(event.get("id") or uuid.uuid4())
        lines += [
            "BEGIN:VEVENT", f"UID:{uid}",
            f"DTSTAMP:{_ical_dt(event.get('t'))}",
            f"DTSTART:{_ical_dt(event.get('t'))}",
            f"SUMMARY:{_ical_escape(str(event.get('label', '')))}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8"), f"{output_key}.ics"


def timeline_to_png(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    # Delegate to the chart export path via a simple scatter conversion.
    from pixie.exporters.charts import _to_static
    events = _timeline_events(raw)
    spec_data = {
        "title": "Timeline",
        "series": [{
            "name": "events",
            "x": [e.get("t") for e in events],
            "y": [1] * len(events),
        }],
    }
    return _to_static(
        {"value": spec_data}, prov=prov, output_key=output_key,
        spec={}, chart_type="chart_scatter", fmt="png",
    )


register_exporter("timeline", "json", timeline_to_json, default=True)
register_exporter("timeline", "csv", timeline_to_csv)
register_exporter("timeline", "ical", timeline_to_ical)
register_exporter("timeline", "png", timeline_to_png)


# --- gantt -------------------------------------------------------------------


def _gantt_tasks(raw: Any) -> list[dict[str, Any]]:
    value = coerce_value(raw)
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and "tasks" in value:
        return list(value["tasks"] or [])
    return []


def gantt_to_csv(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    tasks = _gantt_tasks(raw)
    buf = io.StringIO()
    buf.write(f"# {prov}\n")
    writer = csv.writer(buf)
    writer.writerow(["task", "start", "finish", "resource"])
    for t in tasks:
        writer.writerow([
            csv_scalar(t.get("task") or t.get("name")),
            csv_scalar(t.get("start") or t.get("Start")),
            csv_scalar(t.get("finish") or t.get("Finish")),
            csv_scalar(t.get("resource") or t.get("Resource")),
        ])
    return buf.getvalue().encode("utf-8"), f"{output_key}.csv"


def gantt_to_json(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    payload = {"tasks": _gantt_tasks(raw), "_pixie_provenance": prov}
    return json.dumps(payload, indent=2, default=json_default).encode("utf-8"), f"{output_key}.json"


def gantt_to_png(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    from pixie.exporters import ExporterMissingDependency
    try:
        import plotly.figure_factory as ff  # type: ignore[import-not-found]
        import plotly.io as pio  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "plotly is required for gantt PNG export",
            hint="run `uv add plotly kaleido`",
        ) from exc
    tasks = _gantt_tasks(raw)
    if not tasks:
        raise ExporterMissingDependency(
            "gantt PNG requires at least one task",
            hint="provide tasks in the standard {Task, Start, Finish} shape",
        )
    fig = ff.create_gantt(tasks, group_tasks=True, show_colorbar=True)
    fig.update_layout(title="", margin={"l": 200, "r": 16, "t": 24, "b": 40})
    payload = pio.to_image(fig, format="png", width=1280, height=720, scale=2)
    return payload, f"{output_key}.png"


register_exporter("gantt", "csv", gantt_to_csv, default=True)
register_exporter("gantt", "json", gantt_to_json)
register_exporter("gantt", "png", gantt_to_png)
