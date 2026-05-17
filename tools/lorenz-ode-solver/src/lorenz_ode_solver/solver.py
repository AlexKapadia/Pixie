"""Numerical integration of the Lorenz system using scipy.solve_ivp."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp


@dataclass
class LorenzResult:
    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray


def _rhs(_t: float, state: np.ndarray, sigma: float, rho: float, beta: float) -> list[float]:
    x, y, z = state
    return [sigma * (y - x), x * (rho - z) - y, x * y - beta * z]


def integrate(sigma: float, rho: float, beta: float, t_max: float, dt: float) -> LorenzResult:
    n_samples = max(int(t_max / max(dt, 1e-6)) + 1, 2)
    t_eval = np.linspace(0.0, t_max, n_samples)
    sol = solve_ivp(
        _rhs,
        (0.0, t_max),
        [1.0, 1.0, 1.0],
        method="RK45",
        t_eval=t_eval,
        rtol=1e-7,
        atol=1e-9,
        args=(sigma, rho, beta),
        max_step=max(dt, 1e-3),
    )
    return LorenzResult(t=sol.t, x=sol.y[0], y=sol.y[1], z=sol.y[2])


def poincare_section(result: LorenzResult, plane_z: float = 27.0) -> tuple[np.ndarray, np.ndarray]:
    """Return (x, y) at every upward crossing of z = plane_z."""
    z = result.z
    crossings = np.where((z[:-1] < plane_z) & (z[1:] >= plane_z))[0]
    if crossings.size == 0:
        return np.array([]), np.array([])
    # linear interpolation for sub-step accuracy
    z0, z1 = z[crossings], z[crossings + 1]
    frac = (plane_z - z0) / np.where(z1 - z0 == 0, 1e-9, z1 - z0)
    x_cross = result.x[crossings] + frac * (result.x[crossings + 1] - result.x[crossings])
    y_cross = result.y[crossings] + frac * (result.y[crossings + 1] - result.y[crossings])
    return x_cross, y_cross
