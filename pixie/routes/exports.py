"""Per-artefact + per-run export endpoints.

Backed by :mod:`pixie.exporters`. Streams large zips. Surfaces
:class:`ExporterDegraded` as a 200 response with a header indicating
the fallback format.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pixie import db, exporters
from pixie.artefacts import ArtefactPathError, ArtefactRegistry
from pixie.config import Settings
from pixie.exporters import (
    ExporterDegraded, ExporterError, ExporterMissingDependency, ExporterUnsupported,
)

logger = logging.getLogger("pixie.routes.exports")

router = APIRouter()


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> ArtefactRegistry:
    return request.app.state.artefacts


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RegistryDep = Annotated[ArtefactRegistry, Depends(get_registry)]


# --- per-artefact export -----------------------------------------------------


async def _artefact_to_export_value(
    settings: Settings, registry: ArtefactRegistry, artefact_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None or row.get("deleted_at"):
        raise HTTPException(404, f"artefact {artefact_id} not found")
    try:
        path = registry.abs_for(row["rel_path"])
    except ArtefactPathError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not path.exists():
        raise HTTPException(410, "artefact file no longer on disk")
    # Provide enough context for binary exporters to read the file directly.
    raw = {
        "value": str(path),
        "abs_path": str(path),
        "rel_path": row.get("rel_path"),
        "filename": row.get("filename"),
        "mime": row.get("mime"),
    }
    return raw, row


def _output_type_for(row: dict[str, Any]) -> str:
    """Infer an output type from mime when the artefact wasn't tagged with one."""

    mime = (row.get("mime") or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime in {"text/csv", "text/tab-separated-values"}:
        return "table"
    if mime == "text/markdown":
        return "markdown"
    if mime == "application/json":
        return "kv"
    if mime.startswith("text/"):
        return "text"
    return "file"


@router.get("/api/artefacts/{artefact_id}/export")
async def export_artefact(
    artefact_id: int,
    settings: SettingsDep,
    registry: RegistryDep,
    format: str | None = None,
    output_type: str | None = None,
) -> Response:
    raw, row = await _artefact_to_export_value(settings, registry, artefact_id)
    type_ = output_type or _output_type_for(row)
    try:
        payload, filename = await exporters.export(
            raw, type_, format=format,
            output_key=row.get("output_key") or row.get("filename") or "output",
            tool_id=row.get("tool_id"),
            run_id=row.get("run_id"),
        )
    except ExporterDegraded as exc:
        return Response(
            content=exc.payload, media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{exc.filename}"',
                "X-Pixie-Export-Degraded": exc.actual_format,
                "X-Pixie-Export-Message": str(exc)[:255],
            },
        )
    except ExporterMissingDependency as exc:
        raise HTTPException(503, str(exc)) from exc
    except ExporterUnsupported as exc:
        raise HTTPException(415, str(exc)) from exc
    except ExporterError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=payload, media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/artefacts/{artefact_id}/export")
async def export_artefact_post(
    artefact_id: int,
    settings: SettingsDep,
    registry: RegistryDep,
    format: str | None = None,
    output_type: str | None = None,
) -> Response:
    return await export_artefact(
        artefact_id, settings, registry,
        format=format, output_type=output_type,
    )


# --- per-run-output export (4.6) --------------------------------------------


def _infer_run_output_type(value: Any) -> str:
    """Best-effort output type inference for inline run outputs.

    The run row stores raw outputs without their declared type. We probe
    common shapes; the export pipeline accepts an explicit override via
    ``output_type=`` for callers who know better.
    """

    if isinstance(value, dict):
        if "_artefact_id" in value:
            return value.get("output_type") or "file"
        if "data" in value and "layout" in value:
            # plotly figure dict
            return "chart_line"
        if "columns" in value and "rows" in value:
            return "table"
        return "kv"
    if isinstance(value, list):
        if value and all(isinstance(r, dict) for r in value):
            return "table"
        return "kv"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


async def _resolve_run_output(
    settings: Settings, run_id: str, output_key: str
) -> tuple[dict[str, Any], Any]:
    run_row = await db.get_run(settings.db_path, run_id)
    if run_row is None:
        raise HTTPException(404, f"run {run_id} not found")
    if not run_row.get("outputs_json"):
        raise HTTPException(404, "run has no outputs")
    try:
        envelope = json.loads(run_row["outputs_json"])
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"run outputs are not valid JSON: {exc}") from exc
    outputs = envelope.get("outputs") if isinstance(envelope, dict) else None
    if not isinstance(outputs, dict):
        raise HTTPException(404, "run outputs do not contain an 'outputs' map")
    if output_key not in outputs:
        raise HTTPException(404, f"output {output_key!r} not found in run")
    return run_row, outputs[output_key]


@router.get("/api/runs/{run_id}/outputs/{output_key}/formats")
async def supported_formats_for_run_output(
    run_id: str,
    output_key: str,
    settings: SettingsDep,
    output_type: str | None = None,
) -> dict[str, Any]:
    """Return the list of format ids the exporter supports for this output."""

    _run_row, value = await _resolve_run_output(settings, run_id, output_key)
    type_ = output_type or _infer_run_output_type(value)
    try:
        formats = exporters.supported_formats(type_)
        default = exporters.default_format(type_)
    except ExporterUnsupported:
        formats = []
        default = None
    return {
        "run_id": run_id,
        "output_key": output_key,
        "output_type": type_,
        "default": default,
        "supported": formats,
    }


@router.get("/api/runs/{run_id}/outputs/{output_key}/export")
async def export_run_output(
    run_id: str,
    output_key: str,
    settings: SettingsDep,
    registry: RegistryDep,
    format: str | None = None,
    output_type: str | None = None,
) -> Response:
    """Export ONE inline output from a run as bytes with proper headers."""

    run_row, value = await _resolve_run_output(settings, run_id, output_key)
    type_ = output_type or _infer_run_output_type(value)

    # When the value is a reference-handle to an artefact, defer to the
    # artefact exporter so we stream the real file rather than the handle.
    if isinstance(value, dict) and value.get("_artefact_id"):
        return await export_artefact(
            int(value["_artefact_id"]), settings, registry,
            format=format, output_type=output_type or type_,
        )

    raw = value if isinstance(value, dict) else {"value": value}
    try:
        payload, filename = await exporters.export(
            raw, type_, format=format,
            output_key=output_key,
            tool_id=run_row.get("tool_id"),
            run_id=run_id,
        )
    except ExporterDegraded as exc:
        media = "text/html; charset=utf-8" if exc.actual_format == "html" else "application/octet-stream"
        return Response(
            content=exc.payload,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{exc.filename}"',
                "X-Pixie-Export-Degraded": exc.actual_format,
                "X-Pixie-Export-Message": str(exc)[:255],
            },
        )
    except ExporterMissingDependency as exc:
        raise HTTPException(503, str(exc)) from exc
    except ExporterUnsupported as exc:
        raise HTTPException(415, str(exc)) from exc
    except ExporterError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=payload, media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/artefacts/{artefact_id}/formats")
async def supported_formats_for_artefact(
    artefact_id: int,
    settings: SettingsDep,
) -> dict[str, Any]:
    row = await db.get_artefact(settings.db_path, artefact_id)
    if row is None or row.get("deleted_at"):
        raise HTTPException(404, "artefact not found")
    type_ = _output_type_for(row)
    try:
        formats = exporters.supported_formats(type_)
        default = exporters.default_format(type_)
    except ExporterUnsupported:
        formats = []; default = None
    return {"output_type": type_, "default": default, "supported": formats}


# --- run export --------------------------------------------------------------


def _zip_stream(run_row: dict[str, Any], artefact_rows: list[dict[str, Any]],
                 registry: ArtefactRegistry, prov: str):
    """Yield chunks for a streaming zip response."""

    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    # Write metadata first.
    z.writestr("meta.json", json.dumps({
        "tool_id": run_row.get("tool_id"),
        "run_id": run_row.get("id"),
        "started_at": run_row.get("started_at"),
        "finished_at": run_row.get("finished_at"),
        "status": run_row.get("status"),
        "label": run_row.get("label"),
        "_pixie_provenance": prov,
    }, indent=2, default=str))
    if run_row.get("inputs_json"):
        z.writestr("inputs.json", run_row["inputs_json"])
    if run_row.get("outputs_json"):
        z.writestr("outputs.json", run_row["outputs_json"])
    report_lines = [f"# Run {run_row.get('id')}", "",
                     f"Tool: {run_row.get('tool_id')}",
                     f"Status: {run_row.get('status')}",
                     f"Started: {run_row.get('started_at')}",
                     f"Finished: {run_row.get('finished_at')}", "",
                     "## Artefacts", ""]
    for art in artefact_rows:
        report_lines.append(
            f"- {art.get('filename')} ({art.get('mime')}, {art.get('size_bytes')} bytes)"
        )
    z.writestr("report.md", "\n".join(report_lines) + "\n")
    yield buf.getvalue()
    buf.seek(0); buf.truncate()

    for art in artefact_rows:
        try:
            path = registry.abs_for(art["rel_path"])
        except ArtefactPathError:
            continue
        if not path.exists():
            continue
        arcname = f"artefacts/{art.get('filename') or path.name}"
        with z.open(arcname, "w") as dst, path.open("rb") as src:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
                if buf.tell() >= (1 << 20):
                    yield buf.getvalue()
                    buf.seek(0); buf.truncate()
        if buf.tell():
            yield buf.getvalue()
            buf.seek(0); buf.truncate()
    z.close()
    if buf.tell():
        yield buf.getvalue()


@router.get("/api/runs/{run_id}/report")
async def export_run_report(
    run_id: str,
    settings: SettingsDep,
    registry: RegistryDep,
    include_assets: bool = True,
) -> StreamingResponse:
    run_row = await db.get_run(settings.db_path, run_id)
    if run_row is None:
        raise HTTPException(404, f"run {run_id} not found")
    artefact_rows = await db.list_artefacts(
        settings.db_path, run_id=run_id, limit=10_000,
    ) if include_assets else []
    prov = exporters.make_provenance(
        tool_id=run_row.get("tool_id"), run_id=run_id, output_key=None,
    )
    short = run_id[:8]
    filename = f"{run_row.get('tool_id', 'run')}-{short}.zip"
    return StreamingResponse(
        _zip_stream(run_row, artefact_rows, registry, prov),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- bulk + clipboard --------------------------------------------------------


class BulkExportRequest(BaseModel):
    run_ids: list[str] = Field(default_factory=list)
    artefact_ids: list[int] = Field(default_factory=list)


@router.post("/api/exports/bulk")
async def bulk_export(
    payload: BulkExportRequest,
    settings: SettingsDep,
    registry: RegistryDep,
) -> StreamingResponse:
    if not payload.run_ids and not payload.artefact_ids:
        raise HTTPException(422, "supply run_ids or artefact_ids (at least one)")

    async def gen():
        buf = io.BytesIO()
        z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
        index_rows = [["run_id", "tool_id", "filename", "size_bytes", "sha256"]]
        for run_id in payload.run_ids:
            run_row = await db.get_run(settings.db_path, run_id)
            if not run_row:
                continue
            arts = await db.list_artefacts(settings.db_path, run_id=run_id, limit=10_000)
            for art in arts:
                index_rows.append([
                    run_id, run_row.get("tool_id"), art.get("filename"),
                    str(art.get("size_bytes")), art.get("sha256"),
                ])
                try:
                    src = registry.abs_for(art["rel_path"])
                    if src.exists():
                        z.write(src, arcname=f"runs/{run_id}/{art.get('filename')}")
                except ArtefactPathError:
                    continue
        for art_id in payload.artefact_ids:
            art = await db.get_artefact(settings.db_path, art_id)
            if not art:
                continue
            try:
                src = registry.abs_for(art["rel_path"])
            except ArtefactPathError:
                continue
            if src.exists():
                z.write(src, arcname=f"orphan_artefacts/{art.get('filename')}")
        index_csv = "\n".join(",".join(r) for r in index_rows) + "\n"
        z.writestr("index.csv", index_csv)
        z.close()
        yield buf.getvalue()

    filename = f"pixie-export-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
    return StreamingResponse(
        gen(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/clipboard")
async def clipboard(
    settings: SettingsDep,
    registry: RegistryDep,
    run_id: str | None = None,
    output_key: str | None = None,
    artefact_id: int | None = None,
    fmt: str = "text",
) -> Response:
    if artefact_id is not None:
        raw, row = await _artefact_to_export_value(settings, registry, artefact_id)
        type_ = _output_type_for(row)
        target_fmt = "txt" if fmt == "text" else fmt
        try:
            payload, _ = await exporters.export(
                raw, type_, format=target_fmt,
                output_key=row.get("output_key") or "output",
                tool_id=row.get("tool_id"), run_id=row.get("run_id"),
            )
            return Response(content=payload, media_type="text/plain; charset=utf-8")
        except ExporterError as exc:
            raise HTTPException(422, str(exc)) from exc
    if run_id and output_key:
        run_row = await db.get_run(settings.db_path, run_id)
        if not run_row:
            raise HTTPException(404, "run not found")
        outputs = {}
        if run_row.get("outputs_json"):
            try:
                outputs = json.loads(run_row["outputs_json"]).get("outputs") or {}
            except json.JSONDecodeError:
                outputs = {}
        value = outputs.get(output_key)
        if value is None:
            raise HTTPException(404, "output not found in run")
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        if isinstance(value, (dict, list)):
            body = json.dumps(value, indent=2, ensure_ascii=False, default=str)
        else:
            body = str(value)
        return Response(content=body, media_type="text/plain; charset=utf-8")
    raise HTTPException(422, "supply artefact_id, or run_id + output_key")
