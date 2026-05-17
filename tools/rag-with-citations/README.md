# RAG with Citations

Embeds an uploaded text/PDF corpus, retrieves the top-k chunks for a question via TF-IDF cosine similarity, and emits both an extractive markdown answer with citation markers and a streaming answer (optionally via the Anthropic API if `ANTHROPIC_API_KEY` is set in `.env`).

## Install
```
cd tools/rag-with-citations
uv sync
```

## Test
```
uv run pixie validate rag-with-citations --summary
```
