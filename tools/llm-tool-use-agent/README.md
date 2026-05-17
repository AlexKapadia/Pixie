# LLM Tool-Use Agent

A streaming agent that can use a safe arithmetic calculator and a sandboxed web-search stub. If `ANTHROPIC_API_KEY` is present in `.env`, it routes through `claude-3-5-haiku-latest` with native tool calling; otherwise a deterministic local agent answers using simple intent matching, so the tool always works offline.

## Install
```
cd tools/llm-tool-use-agent
uv sync
```

## Test
```
uv run pixie validate llm-tool-use-agent --summary
```
