"""Default streaming generator for {{TOOL_NAME}}.

Replace ``generate_reply`` with a call to your LLM of choice. The
contract is: yield string chunks; the handler wraps them in SSE
``data:`` frames and the renderer concatenates them on the client.

The default behaviour echoes the latest user message back, one
character at a time with a small delay, so authors can verify the
streaming wiring before integrating a real model.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterable

CHARACTER_DELAY_SECONDS = 0.02


async def generate_reply(
    system_prompt: str,  # noqa: ARG001 — kept for parity with real LLMs
    messages: Iterable["object"],
) -> AsyncIterator[str]:
    user_text = ""
    for message in messages:
        role = getattr(message, "role", None)
        content = getattr(message, "content", "")
        if role == "user":
            user_text = content
    reply = f"echo: {user_text}" if user_text else "ready."
    for character in reply:
        yield character
        await asyncio.sleep(CHARACTER_DELAY_SECONDS)
