"""Training loop for {{TOOL_NAME}}.

The default implementation is a deterministic decaying-loss generator so
the streaming wiring works without PyTorch installed. Install the
``runtime`` group (``uv sync --group runtime``) and replace
``train_step`` with a real torch update once you're ready.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class EpochResult:
    epoch: int
    loss: float
    val_loss: float


async def train(
    epochs: int,
    learning_rate: float,
) -> AsyncIterator[EpochResult]:
    """Yield one :class:`EpochResult` per epoch.

    The placeholder loss decays exponentially with a small noise term so
    plots look realistic out of the box.
    """

    decay_rate = max(0.05, min(0.6, learning_rate * 5.0))
    for epoch in range(1, max(1, epochs) + 1):
        baseline = math.exp(-decay_rate * epoch)
        loss = round(baseline + 0.02 * math.sin(epoch), 4)
        val_loss = round(baseline * 1.07 + 0.03 * math.cos(epoch), 4)
        yield EpochResult(epoch=epoch, loss=loss, val_loss=val_loss)
        await asyncio.sleep(0.05)
