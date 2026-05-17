"""Text + markdown + code + log + stream_text + latex exporters.

Grouped for cohesion: every type in this module exports plain-ish text
with format-specific provenance placement and HTML/PDF rendering.
"""

from __future__ import annotations

import html
import io
import json
from pathlib import Path
from typing import Any

from pixie.exporters import (
    ExporterError,
    ExporterMissingDependency,
    register_exporter,
)
from pixie.exporters._common import coerce_path, coerce_value, html_shell


# --- text --------------------------------------------------------------------


def _text_value(raw: Any) -> str:
    value = coerce_value(raw)
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    if isinstance(value, dict):
        # Some tools return {text: "..."} for richer text outputs.
        for key in ("text", "value", "body"):
            if isinstance(value.get(key), str):
                return value[key]
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return str(value)


def text_to_txt(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = f"# {prov}\n\n{_text_value(raw)}\n"
    return body.encode("utf-8"), f"{output_key}.txt"


def text_to_md(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = _text_value(raw).replace("\\", "\\\\").replace("`", "\\`")
    payload = f"<!-- {prov} -->\n\n```\n{body}\n```\n"
    return payload.encode("utf-8"), f"{output_key}.md"


def text_to_html(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = html.escape(_text_value(raw))
    return html_shell(body, prov, pre=True).encode("utf-8"), f"{output_key}.html"


def text_to_json(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    payload = {output_key: _text_value(raw), "_pixie_provenance": prov}
    return (
        json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
        f"{output_key}.json",
    )


def text_to_pdf(raw, *, prov, output_key, opts, **_) -> tuple[bytes, str]:
    # Reportlab-free: render via Pillow as a single A4 page with text. This
    # keeps PDF working without forcing the Playwright Chromium download.
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "Pillow is required for text PDF export",
            hint="install pillow (run `pixie doctor` for guidance)",
        ) from exc
    body = _text_value(raw)
    return _render_text_as_pdf(body, prov, output_key, Image, ImageDraw, ImageFont)


def _render_text_as_pdf(body, prov, output_key, Image, ImageDraw, ImageFont):
    # 300 DPI A4 portrait = 2480 x 3508; we go 150 DPI to keep file size sane.
    width, height = 1240, 1754
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    margin_x, margin_y = 80, 80
    line_height = 24
    cursor = margin_y
    draw.text((margin_x, cursor), prov[:160], fill=(150, 150, 150), font=font)
    cursor += line_height + 12
    for line in body.splitlines() or [""]:
        while len(line) > 0 and cursor + line_height < height - margin_y:
            chunk, line = line[:96], line[96:]
            draw.text((margin_x, cursor), chunk, fill=(20, 20, 20), font=font)
            cursor += line_height
        if line == "":
            cursor += line_height
        if cursor >= height - margin_y:
            break
    out = io.BytesIO()
    canvas.save(out, format="PDF", resolution=150.0)
    return out.getvalue(), f"{output_key}.pdf"


def text_to_docx(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    # python-docx isn't a forced dep; gracefully degrade to .txt with a hint.
    try:
        from docx import Document  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExporterMissingDependency(
            "python-docx is required for .docx export",
            hint="run `uv pip install python-docx`",
        ) from exc
    body = _text_value(raw)
    doc = Document()
    doc.core_properties.comments = prov[:255]
    for paragraph in body.split("\n\n"):
        doc.add_paragraph(paragraph)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), f"{output_key}.docx"


register_exporter("text", "txt", text_to_txt, default=True)
register_exporter("text", "md", text_to_md)
register_exporter("text", "html", text_to_html)
register_exporter("text", "json", text_to_json)
register_exporter("text", "pdf", text_to_pdf)
register_exporter("text", "docx", text_to_docx)


# --- stream_text -------------------------------------------------------------


register_exporter("stream_text", "txt", text_to_txt, default=True)
register_exporter("stream_text", "md", text_to_md)


# --- log ---------------------------------------------------------------------


def log_to_txt(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    return text_to_txt(raw, prov=prov, output_key=output_key)


def log_to_jsonl(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    lines = _text_value(raw).splitlines()
    buf = io.StringIO()
    buf.write(json.dumps({"_pixie_provenance": prov}) + "\n")
    for line in lines:
        buf.write(json.dumps({"line": line}) + "\n")
    return buf.getvalue().encode("utf-8"), f"{output_key}.jsonl"


def log_to_csv(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    import csv
    buf = io.StringIO()
    buf.write(f"# {prov}\n")
    writer = csv.writer(buf)
    writer.writerow(["line"])
    for line in _text_value(raw).splitlines():
        writer.writerow([line])
    return buf.getvalue().encode("utf-8"), f"{output_key}.csv"


register_exporter("log", "txt", log_to_txt, default=True)
register_exporter("log", "jsonl", log_to_jsonl)
register_exporter("log", "csv", log_to_csv)


# --- markdown ----------------------------------------------------------------


def markdown_to_md(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = _text_value(raw)
    payload = f"<!-- {prov} -->\n\n{body}\n"
    return payload.encode("utf-8"), f"{output_key}.md"


def markdown_to_html(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = _text_value(raw)
    try:
        from markdown_it import MarkdownIt  # type: ignore[import-not-found]
        md = MarkdownIt("commonmark", {"html": False, "linkify": True})
        try:
            md.enable(["table", "strikethrough"])
        except Exception:  # noqa: BLE001
            pass
        rendered = md.render(body)
    except ImportError:
        # Fallback: render as preformatted text.
        rendered = f"<pre>{html.escape(body)}</pre>"
    return html_shell(rendered, prov, pre=False).encode("utf-8"), f"{output_key}.html"


def markdown_to_pdf(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    return text_to_pdf(raw, prov=prov, output_key=output_key, opts={})


def markdown_to_txt(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    return text_to_txt(raw, prov=prov, output_key=output_key)


def markdown_to_docx(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    return text_to_docx(raw, prov=prov, output_key=output_key)


register_exporter("markdown", "md", markdown_to_md, default=True)
register_exporter("markdown", "html", markdown_to_html)
register_exporter("markdown", "pdf", markdown_to_pdf)
register_exporter("markdown", "txt", markdown_to_txt)
register_exporter("markdown", "docx", markdown_to_docx)


# --- code --------------------------------------------------------------------


_LANG_EXT = {
    "python": ".py", "javascript": ".js", "typescript": ".ts",
    "rust": ".rs", "go": ".go", "java": ".java", "kotlin": ".kt",
    "sql": ".sql", "bash": ".sh", "shell": ".sh", "ruby": ".rb",
    "php": ".php", "c": ".c", "cpp": ".cpp", "csharp": ".cs",
    "html": ".html", "css": ".css", "yaml": ".yml", "json": ".json",
    "xml": ".xml", "toml": ".toml", "markdown": ".md", "text": ".txt",
}

_LANG_COMMENT = {
    "python": "#", "ruby": "#", "bash": "#", "shell": "#", "yaml": "#",
    "toml": "#", "javascript": "//", "typescript": "//", "rust": "//",
    "go": "//", "java": "//", "kotlin": "//", "c": "//", "cpp": "//",
    "csharp": "//", "php": "//", "sql": "--", "html": "<!--",
    "css": "/*", "xml": "<!--", "markdown": "<!--", "json": "//",
}


def _code_meta(spec: dict[str, Any] | None) -> tuple[str, str, str]:
    language = ((spec or {}).get("language") or "text").lower()
    ext = _LANG_EXT.get(language, ".txt")
    comment_prefix = _LANG_COMMENT.get(language, "#")
    return language, ext, comment_prefix


def code_to_source(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    language, ext, comment = _code_meta(spec)
    body = _text_value(raw)
    if comment in {"<!--", "/*"}:
        prov_line = f"{comment} {prov} {'-->' if comment == '<!--' else '*/'}\n\n"
    else:
        prov_line = f"{comment} {prov}\n\n"
    payload = prov_line + body
    return payload.encode("utf-8"), f"{output_key}{ext}"


def code_to_html(raw, *, prov, output_key, spec, **_) -> tuple[bytes, str]:
    language, _, _ = _code_meta(spec)
    body = _text_value(raw)
    try:
        from pygments import highlight  # type: ignore[import-not-found]
        from pygments.formatters import HtmlFormatter  # type: ignore[import-not-found]
        from pygments.lexers import (  # type: ignore[import-not-found]
            TextLexer, get_lexer_by_name,
        )
        try:
            lexer = get_lexer_by_name(language)
        except Exception:  # noqa: BLE001
            lexer = TextLexer()
        formatter = HtmlFormatter(
            full=True, linenos=True, noclasses=True, style="bw",
            title=f"Pixie export -- {prov}",
        )
        rendered = highlight(body, lexer, formatter)
    except ImportError:
        rendered = html_shell(html.escape(body), prov, pre=True)
    return rendered.encode("utf-8"), f"{output_key}.html"


register_exporter("code", "source", code_to_source, default=True)
register_exporter("code", "txt", code_to_source)
register_exporter("code", "html", code_to_html)


# --- latex -------------------------------------------------------------------


def latex_to_tex(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = _text_value(raw)
    payload = f"% {prov}\n{body}\n"
    return payload.encode("utf-8"), f"{output_key}.tex"


def latex_to_html(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = _text_value(raw)
    katex_html = (
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.47/dist/katex.min.css">\n'
        '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.47/dist/katex.min.js"></script>\n'
        '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.47/dist/contrib/auto-render.min.js" '
        'onload="renderMathInElement(document.body, {delimiters: ['
        '{left: \'$$\', right: \'$$\', display: true},'
        '{left: \'$\', right: \'$\', display: false}]});"></script>\n'
        f"<div>{html.escape(body)}</div>"
    )
    return html_shell(katex_html, prov, pre=False).encode("utf-8"), f"{output_key}.html"


def latex_to_pdf(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    return text_to_pdf(raw, prov=prov, output_key=output_key, opts={})


def latex_to_png(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    raise ExporterMissingDependency(
        "LaTeX -> PNG requires Playwright Chromium",
        hint="run `pixie doctor --install-playwright` for the headless browser",
    )


register_exporter("latex", "tex", latex_to_tex, default=True)
register_exporter("latex", "html", latex_to_html)
register_exporter("latex", "pdf", latex_to_pdf)
register_exporter("latex", "png", latex_to_png)


# --- diff --------------------------------------------------------------------


def diff_to_patch(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = _text_value(raw)
    payload = f"# pixie provenance: {prov}\n{body}\n"
    return payload.encode("utf-8"), f"{output_key}.patch"


def diff_to_html(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    body = _text_value(raw)
    try:
        from pygments import highlight  # type: ignore[import-not-found]
        from pygments.formatters import HtmlFormatter  # type: ignore[import-not-found]
        from pygments.lexers.diff import DiffLexer  # type: ignore[import-not-found]
        rendered = highlight(
            body, DiffLexer(),
            HtmlFormatter(full=True, noclasses=True, style="bw"),
        )
    except ImportError:
        rendered = html_shell(html.escape(body), prov, pre=True)
    return rendered.encode("utf-8"), f"{output_key}.html"


def diff_to_pdf(raw, *, prov, output_key, **_) -> tuple[bytes, str]:
    return text_to_pdf(raw, prov=prov, output_key=output_key, opts={})


register_exporter("diff", "patch", diff_to_patch, default=True)
register_exporter("diff", "html", diff_to_html)
register_exporter("diff", "pdf", diff_to_pdf)
