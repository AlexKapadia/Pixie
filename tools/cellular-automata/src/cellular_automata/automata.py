"""Conway's Game of Life + Wolfram 1-D elementary CAs."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CAResult:
    grid: np.ndarray  # 2-D uint8 of the final visualised state
    counts: list[int]  # live-cell count per generation


def _conway_step(state: np.ndarray) -> np.ndarray:
    neighbours = sum(
        np.roll(np.roll(state, dy, axis=0), dx, axis=1)
        for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)
    )
    return ((neighbours == 3) | ((state == 1) & (neighbours == 2))).astype(np.uint8)


def _conway(width: int, generations: int, seed: int | None) -> CAResult:
    rng = np.random.default_rng(seed)
    height = max(width // 2, 32)
    state = (rng.random((height, width)) < 0.25).astype(np.uint8)
    counts = [int(state.sum())]
    for _ in range(generations):
        state = _conway_step(state)
        counts.append(int(state.sum()))
    return CAResult(grid=state * 255, counts=counts)


def _elementary(rule_number: int, width: int, generations: int, seed: int | None) -> CAResult:
    rule_bits = np.array([(rule_number >> i) & 1 for i in range(8)], dtype=np.uint8)
    rng = np.random.default_rng(seed)
    row = (rng.random(width) < 0.5).astype(np.uint8) if rule_number != 30 else np.zeros(width, dtype=np.uint8)
    if rule_number == 30:
        row[width // 2] = 1
    history = np.zeros((generations, width), dtype=np.uint8)
    history[0] = row
    counts = [int(row.sum())]
    for gen in range(1, generations):
        left = np.roll(row, 1)
        right = np.roll(row, -1)
        pattern = (left << 2) | (row << 1) | right
        row = rule_bits[pattern]
        history[gen] = row
        counts.append(int(row.sum()))
    return CAResult(grid=history * 255, counts=counts)


def evolve(rule: str, width: int, generations: int, seed: int | None) -> CAResult:
    if rule == "conway":
        return _conway(width, generations, seed)
    rule_map = {"rule30": 30, "rule90": 90, "rule110": 110, "rule184": 184}
    if rule not in rule_map:
        raise ValueError(f"unknown rule {rule!r}")
    return _elementary(rule_map[rule], width, generations, seed)
