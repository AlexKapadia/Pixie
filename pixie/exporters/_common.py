"""Shared helpers for every exporter module.

Keep this module dependency-free (stdlib only). Heavy libs (Pillow,
pyarrow, openpyxl, ffmpeg) are pulled in by the per-type modules.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any


# --- value coercion ----------------------------------------------------------


def coerce_value(raw: Any) -> Any:
    """Strip a Pixie output handle down to its bare value.

    Tools wrap outputs as ``{"value": ...}``. Some values arrive as the
    raw form. This helper accepts either shape.
    """

    if isinstance(raw, dict) and "value" in raw and "_artefact_id" not in raw:
        return raw["value"]
    return raw


def coerce_path(raw: Any) -> Path | None:
    """Return a filesystem Path if ``raw`` references one, else ``None``."""

    if isinstance(raw, Path):
        return raw
    if isinstance(raw, str) and raw:
        candidate = Path(raw)
        if candidate.exists():
            return candidate
        return None
    if isinstance(raw, dict):
        for key in ("abs_path", "path", "rel_path"):
            v = raw.get(key)
            if v:
                p = Path(v)
                if p.exists():
                    return p
    return None


def csv_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)


def write_csv_rows(
    rows: list[dict[str, Any]],
    columns: list[str] | None,
    *,
    prov: str,
    delim: str = ",",
) -> bytes:
    headers = columns or (list(rows[0].keys()) if rows else [])
    buf = io.StringIO()
    buf.write(f"# {prov}\n")
    writer = csv.DictWriter(
        buf, fieldnames=headers, extrasaction="ignore", delimiter=delim,
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({h: csv_scalar(row.get(h)) for h in headers})
    return buf.getvalue().encode("utf-8")


# --- HTML scaffolding --------------------------------------------------------


_HTML_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<meta name="pixie-provenance" content="{prov_attr}" />
<style>
body {{ font-family: 'Inter Tight', -apple-system, system-ui, sans-serif;
       max-width: 880px; margin: 32px auto; padding: 0 24px; color: #111;
       line-height: 1.55; }}
pre, code, kbd {{ font-family: 'JetBrains Mono', ui-monospace, monospace;
                  font-size: 0.92em; }}
pre {{ background: #f6f7f9; border-radius: 6px; padding: 14px 16px;
       overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #e6e7ea; padding: 6px 10px; text-align: left; }}
footer.pixie {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #e6e7ea;
               color: #6b6f76; font-size: 0.85em; }}
</style>
</head>
<body>
{body}
<footer class="pixie">{prov_text}</footer>
</body>
</html>
"""


def html_shell(body: str, prov: str, *, title: str = "Pixie export", pre: bool = False) -> str:
    inner = f"<pre>{_html_escape(body)}</pre>" if pre else body
    return _HTML_SHELL.format(
        title=_html_escape(title),
        prov_attr=_html_attr_escape(prov),
        body=inner,
        prov_text=_html_escape(prov),
    )


def _html_escape(value: str) -> str:
    from html import escape
    return escape(value, quote=False)


def _html_attr_escape(value: str) -> str:
    from html import escape
    return escape(value, quote=True)
