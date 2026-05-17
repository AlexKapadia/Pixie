"""Vectorised leapfrog N-body simulation under Newtonian gravity (G=1)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SOFTENING = 0.05  # avoids singular accelerations on close passes


@dataclass
class Trajectory:
    positions: np.ndarray  # (steps+1, n_bodies, 2)
    energy: np.ndarray     # (steps+1,)
    masses: np.ndarray     # (n_bodies,)


def _accelerations(positions: np.ndarray, masses: np.ndarray) -> np.ndarray:
    delta = positions[None, :, :] - positions[:, None, :]
    distance_sq = np.sum(delta ** 2, axis=-1) + SOFTENING ** 2
    inv_distance_cubed = distance_sq ** (-1.5)
    np.fill_diagonal(inv_distance_cubed, 0.0)
    accel = np.einsum("ij,ijk,j->ik", inv_distance_cubed, delta, masses)
    return accel


def _total_energy(positions: np.ndarray, velocities: np.ndarray, masses: np.ndarray) -> float:
    kinetic = 0.5 * float(np.sum(masses * np.sum(velocities ** 2, axis=-1)))
    delta = positions[None, :, :] - positions[:, None, :]
    distance = np.sqrt(np.sum(delta ** 2, axis=-1) + SOFTENING ** 2)
    inv_distance = np.where(distance > 0, 1.0 / distance, 0.0)
    np.fill_diagonal(inv_distance, 0.0)
    pair_mass = masses[:, None] * masses[None, :]
    potential = -0.5 * float(np.sum(pair_mass * inv_distance))
    return kinetic + potential


def simulate(n_bodies: int, mass_range: float, steps: int, dt: float, seed: int) -> Trajectory:
    rng = np.random.default_rng(seed)
    masses = rng.uniform(0.1, max(mass_range, 0.2), size=n_bodies)
    positions = rng.uniform(-2.0, 2.0, size=(n_bodies, 2))
    velocities = rng.uniform(-0.3, 0.3, size=(n_bodies, 2))
    # remove centre-of-mass drift so the system stays in frame
    velocities -= np.average(velocities, axis=0, weights=masses)

    trajectory = np.zeros((steps + 1, n_bodies, 2))
    energies = np.zeros(steps + 1)
    trajectory[0] = positions
    energies[0] = _total_energy(positions, velocities, masses)

    accel = _accelerations(positions, masses)
    for index in range(1, steps + 1):
        velocities = velocities + 0.5 * dt * accel
        positions = positions + dt * velocities
        accel = _accelerations(positions, masses)
        velocities = velocities + 0.5 * dt * accel
        trajectory[index] = positions
        energies[index] = _total_energy(positions, velocities, masses)

    return Trajectory(positions=trajectory, energy=energies, masses=masses)
