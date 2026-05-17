"""Streaming agent loop. Uses Anthropic when ANTHROPIC_API_KEY is set; otherwise
runs a deterministic local reasoning loop so the contract still works offline."""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import AsyncIterator

from .tools import REGISTRY


@dataclass
class StreamEvent:
    kind: str  # "text" or "tool_call"
    payload: object


async def _local_agent(query: str, enabled_tools: list[str]) -> AsyncIterator[StreamEvent]:
    yield StreamEvent("text", "Thinking about your request... ")
    await asyncio.sleep(0.01)
    arith = re.findall(r"[-+*/().0-9\s]+", query)
    expr = next((s.strip() for s in arith if re.search(r"[0-9].*[-+*/].*[0-9]", s)), None)
    if expr and "calculator" in enabled_tools:
        try:
            answer = REGISTRY["calculator"]["fn"]({"expression": expr})
            yield StreamEvent("tool_call", {"tool": "calculator", "input": expr, "output": answer})
            yield StreamEvent("text", f"\nUsing the calculator, {expr.strip()} = **{answer}**.")
            return
        except Exception:
            pass
    if "web_search" in enabled_tools:
        result = REGISTRY["web_search"]["fn"]({"query": query})
        yield StreamEvent("tool_call", {"tool": "web_search", "input": query, "output": result})
        yield StreamEvent("text", f"\nFrom a quick lookup: {result}")
        return
    yield StreamEvent("text", "I do not have an enabled tool that can help with that question.")


async def _anthropic_agent(messages: list[dict], enabled_tools: list[str]) -> AsyncIterator[StreamEvent]:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    tool_schemas = [REGISTRY[name]["schema"] for name in enabled_tools if name in REGISTRY]
    api_messages = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in ("user", "assistant")]

    while True:
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=512,
            tools=tool_schemas or None,
            messages=api_messages,
        )
        any_tool_used = False
        assistant_blocks: list[dict] = []
        for block in response.content:
            if block.type == "text":
                yield StreamEvent("text", block.text)
                assistant_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                any_tool_used = True
                tool_fn = REGISTRY.get(block.name, {}).get("fn")
                if tool_fn is None:
                    result = f"Tool {block.name!r} is not available."
                else:
                    try:
                        result = tool_fn(block.input or {})
                    except Exception as exc:
                        result = f"Tool error: {exc}"
                yield StreamEvent("tool_call", {"tool": block.name, "input": block.input, "output": result})
                assistant_blocks.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
                api_messages.append({"role": "assistant", "content": assistant_blocks})
                api_messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": block.id, "content": str(result)},
                ]})
                assistant_blocks = []
                break
        if not any_tool_used:
            return


async def run_agent(messages: list[dict], enabled_tools: list[str]) -> AsyncIterator[StreamEvent]:
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            async for event in _anthropic_agent(messages, enabled_tools):
                yield event
            return
        except Exception as exc:
            yield StreamEvent("text", f"\n(Anthropic call failed: {exc}. Falling back to local agent.)\n")
    query = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            query = message.get("content", "")
            break
    async for event in _local_agent(query, enabled_tools):
        yield event
