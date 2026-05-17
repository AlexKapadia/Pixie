"""2-D gaussian kernel density estimation utilities."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import numpy as np
from scipy.stats import gaussian_kde


@dataclass
class KdeResult:
    grid_lats: np.ndarray
    grid_lngs: np.ndarray
    density: np.ndarray
    peak_lat: float
    peak_lng: float
    peak_density: float


def parse_csv(text: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    reader = csv.DictReader(io.StringIO(text))
    lats: list[float] = []
    lngs: list[float] = []
    weights: list[float] = []
    if reader.fieldnames is None:
        raise ValueError("CSV must have a header row including 'lat' and 'lng'.")
    lower = {n.lower(): n for n in reader.fieldnames}
    if "lat" not in lower or "lng" not in lower:
        raise ValueError("CSV must contain 'lat' and 'lng' columns.")
    lat_key, lng_key = lower["lat"], lower["lng"]
    weight_key = lower.get("weight")
    for row in reader:
        try:
            lats.append(float(row[lat_key]))
            lngs.append(float(row[lng_key]))
            weights.append(float(row[weight_key]) if weight_key and row.get(weight_key) else 1.0)
        except (TypeError, ValueError):
            continue
    if not lats:
        raise ValueError("No valid rows found in CSV.")
    return np.asarray(lats), np.asarray(lngs), np.asarray(weights)


def estimate(
    lats: np.ndarray,
    lngs: np.ndarray,
    weights: np.ndarray,
    bandwidth: float = 1.0,
    grid_resolution: int = 60,
) -> KdeResult:
    pts = np.vstack([lngs, lats])
    if pts.shape[1] < 2 or np.allclose(pts.std(axis=1), 0):
        # Degenerate input — degenerate output, but valid.
        lat_c, lng_c = float(lats.mean()), float(lngs.mean())
        return KdeResult(
            grid_lats=np.array([lat_c]),
            grid_lngs=np.array([lng_c]),
            density=np.array([[1.0]]),
            peak_lat=lat_c,
            peak_lng=lng_c,
            peak_density=1.0,
        )

    kde = gaussian_kde(pts, weights=weights, bw_method="scott")
    kde.set_bandwidth(kde.factor * bandwidth)

    pad = 0.1
    lat_min, lat_max = float(lats.min()) - pad, float(lats.max()) + pad
    lng_min, lng_max = float(lngs.min()) - pad, float(lngs.max()) + pad
    g_lats = np.linspace(lat_min, lat_max, grid_resolution)
    g_lngs = np.linspace(lng_min, lng_max, grid_resolution)
    mesh_lng, mesh_lat = np.meshgrid(g_lngs, g_lats)
    sample = np.vstack([mesh_lng.ravel(), mesh_lat.ravel()])
    density = kde(sample).reshape(grid_resolution, grid_resolution)

    peak_idx = int(np.argmax(density))
    peak_row, peak_col = divmod(peak_idx, grid_resolution)
    return KdeResult(
        grid_lats=g_lats,
        grid_lngs=g_lngs,
        density=density,
        peak_lat=float(g_lats[peak_row]),
        peak_lng=float(g_lngs[peak_col]),
        peak_density=float(density.max()),
    )
