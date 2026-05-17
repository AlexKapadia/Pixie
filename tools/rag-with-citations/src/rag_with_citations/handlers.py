"""FastAPI app for the RAG-with-citations tool."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .retriever import CitationIndex, Chunk, Hit, chunk_text

TOOL_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((TOOL_DIR / "tool.json").read_text(encoding="utf-8"))

SAMPLE_CORPUS: list[tuple[str, str]] = [
    ("intro.md", "Pixie is a local-first dashboard for personal tools and models. It spawns each tool as a separate FastAPI process and proxies requests through a single host."),
    ("architecture.md", "Tools live under tools/<id> and declare their schema in tool.json. Each tool exposes /schema, /healthz, /run, and optionally /stream for SSE."),
    ("retrieval.md", "Retrieval-augmented generation combines vector search with a language model. The retriever returns the most relevant chunks for a query; the generator conditions on those chunks plus the question."),
    ("validator.md", "The validator runs every check in sequence: schema validity, file presence, dependency resolution, spawn, healthcheck, sample run, output conformance, streaming handshake, and reference fixtures."),
]


class Inputs(BaseModel):
    documents: str | None = None
    query: str = "What is the main topic of these documents?"
    top_k: int = 4


class RunRequest(BaseModel):
    model_config = {"extra": "allow"}
    run_id: str | None = None
    inputs: Inputs | None = None


def _decode_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _load_chunks(raw: str | None) -> list[Chunk]:
    if not raw:
        return [c for source, text in SAMPLE_CORPUS for c in chunk_text(text, source)]
    if raw.startswith("data:"):
        _, _, b64 = raw.partition(",")
        try:
            data = base64.b64decode(b64)
        except Exception:
            data = b""
        if data[:4] == b"%PDF":
            return chunk_text(_decode_pdf(data), "uploaded.pdf")
        if data[:8] == b"\x89PNG\r\n\x1a\n" or not data:
            return [c for source, text in SAMPLE_CORPUS for c in chunk_text(text, source)]
        text = data.decode("utf-8", errors="ignore")
        return chunk_text(text, "uploaded.txt")
    path = Path(raw)
    if path.is_file():
        if path.suffix.lower() == ".pdf":
            return chunk_text(_decode_pdf(path.read_bytes()), path.name)
        return chunk_text(path.read_text(encoding="utf-8", errors="ignore"), path.name)
    return chunk_text(raw, "inline.txt")


def _format_answer_md(hits: list[Hit], query: str) -> str:
    if not hits:
        return f"No relevant context found for: **{query}**"
    lines = [f"**Answer (extractive):** Based on the retrieved evidence for *{query}*:\n"]
    for index, hit in enumerate(hits, start=1):
        snippet = hit.chunk.text.replace("\n", " ").strip()
        if len(snippet) > 240:
            snippet = snippet[:240] + "..."
        lines.append(f"- {snippet} [{index}]")
    lines.append("\n**Citations**")
    for index, hit in enumerate(hits, start=1):
        lines.append(f"[{index}] {hit.chunk.source} ({hit.chunk.chunk_id}) — score {hit.score:.3f}")
    return "\n".join(lines)


async def _stream_answer(hits: list[Hit], query: str) -> AsyncIterator[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            context = "\n\n".join(f"[{i+1}] {h.chunk.text}" for i, h in enumerate(hits))
            system = "Answer the user's question using ONLY the numbered context chunks. Cite chunks like [1], [2]."
            user = f"Question: {query}\n\nContext:\n{context}"
            with client.messages.stream(
                model="claude-3-5-haiku-latest",
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                for text in stream.text_stream:
                    yield text
            return
        except Exception:
            pass  # fall through to extractive
    text = _format_answer_md(hits, query)
    for token in text.split(" "):
        yield token + " "
        await asyncio.sleep(0.005)


def _retrieved_table(hits: list[Hit]) -> dict[str, Any]:
    rows = [
        {
            "id": h.chunk.chunk_id,
            "source": h.chunk.source,
            "score": round(h.score, 4),
            "preview": (h.chunk.text[:160] + "...") if len(h.chunk.text) > 160 else h.chunk.text,
        }
        for h in hits
    ]
    return {
        "columns": [
            {"key": "id", "label": "ID", "type": "string"},
            {"key": "source", "label": "Source", "type": "string"},
            {"key": "score", "label": "Score", "type": "number"},
            {"key": "preview", "label": "Preview", "type": "string"},
        ],
        "rows": rows,
    }


def build_app() -> FastAPI:
    load_dotenv(TOOL_DIR / ".env")
    app = FastAPI(title=SCHEMA["name"])
    pending: dict[str, tuple[list[Hit], str]] = {}

    @app.get("/schema")
    async def get_schema() -> dict[str, Any]:
        return SCHEMA

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/run")
    async def run(payload: RunRequest) -> dict[str, Any]:
        run_id = payload.run_id or str(uuid.uuid4())
        if payload.inputs is not None:
            inputs = payload.inputs
        else:
            flat = payload.model_dump(exclude_none=True)
            flat.pop("run_id", None)
            flat.pop("inputs", None)
            inputs = Inputs.model_validate(flat) if flat else Inputs()
        chunks = _load_chunks(inputs.documents)
        index = CitationIndex(chunks)
        hits = index.query(inputs.query, inputs.top_k)
        pending[run_id] = (hits, inputs.query)
        return {
            "run_id": run_id,
            "answer_md": _format_answer_md(hits, inputs.query),
            "retrieved": _retrieved_table(hits),
            "answer_stream": "",
        }

    @app.get("/stream")
    async def stream(run_id: str, request: Request) -> StreamingResponse:
        hits, query = pending.pop(run_id, ([], ""))

        async def event_stream() -> AsyncIterator[bytes]:
            try:
                async for chunk in _stream_answer(hits, query):
                    if await request.is_disconnected():
                        return
                    payload = json.dumps({"chunk": chunk, "done": False})
                    yield f"data: {payload}\n\n".encode("utf-8")
                yield b"data: " + json.dumps({"chunk": "", "done": True}).encode("utf-8") + b"\n\n"
            except asyncio.CancelledError:
                raise

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/cancel")
    async def cancel(run_id: str) -> Response:
        pending.pop(run_id, None)
        return Response(status_code=204)

    return app
