"""Lotka-Volterra integration using scipy.integrate.odeint."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.integrate import odeint


@dataclass
class LvResult:
    t: np.ndarray
    prey: np.ndarray
    predator: np.ndarray


def _rhs(state, _t, alpha, beta, gamma, delta):
    prey, predator = state
    return [alpha * prey - beta * prey * predator,
            delta * prey * predator - gamma * predator]


def simulate(
    alpha: float,
    beta: float,
    gamma: float,
    delta: float,
    initial_prey: float,
    initial_predator: float,
    t_max: float,
    samples: int = 2000,
) -> LvResult:
    t = np.linspace(0.0, max(t_max, 0.1), samples)
    sol = odeint(
        _rhs,
        [max(initial_prey, 1e-6), max(initial_predator, 1e-6)],
        t,
        args=(alpha, beta, gamma, delta),
        rtol=1e-7,
        atol=1e-9,
    )
    return LvResult(t=t, prey=sol[:, 0], predator=sol[:, 1])


def equilibria(alpha: float, beta: float, gamma: float, delta: float) -> dict[str, dict[str, float]]:
    """Two fixed points of the Lotka-Volterra system."""
    trivial = {"prey": 0.0, "predator": 0.0}
    coexistence = {
        "prey": float(gamma / delta) if delta else float("inf"),
        "predator": float(alpha / beta) if beta else float("inf"),
    }
    return {"trivial": trivial, "coexistence": coexistence}
