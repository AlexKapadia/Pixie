"""TSP solver: OR-Tools for small/medium, nearest-neighbour fallback."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two points."""
    r = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_matrix(points: Sequence[tuple[float, float]]) -> np.ndarray:
    n = len(points)
    matrix = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(points[i][0], points[i][1], points[j][0], points[j][1])
            matrix[i, j] = matrix[j, i] = d
    return matrix


def _solve_ortools(matrix: np.ndarray, return_to_start: bool) -> list[int]:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    n = matrix.shape[0]
    if return_to_start:
        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    else:
        manager = pywrapcp.RoutingIndexManager(n, 1, [0], [n - 1])
    routing = pywrapcp.RoutingModel(manager)

    scaled = (matrix * 1000.0).astype(np.int64)

    def distance_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(scaled[from_node, to_node])

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = 5

    solution = routing.SolveWithParameters(params)
    if not solution:
        return _solve_nearest_neighbour(matrix, return_to_start)

    order: list[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        order.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))
    if return_to_start:
        order.append(order[0])
    else:
        order.append(manager.IndexToNode(index))
    return order


def _solve_nearest_neighbour(matrix: np.ndarray, return_to_start: bool) -> list[int]:
    n = matrix.shape[0]
    visited = {0}
    order = [0]
    current = 0
    while len(visited) < n:
        candidates = [(matrix[current, j], j) for j in range(n) if j not in visited]
        _, next_node = min(candidates)
        order.append(next_node)
        visited.add(next_node)
        current = next_node
    if return_to_start:
        order.append(0)
    return order


def solve(points: Sequence[tuple[float, float]], return_to_start: bool = True) -> list[int]:
    if len(points) < 2:
        return list(range(len(points)))
    matrix = distance_matrix(points)
    if len(points) <= 30:
        try:
            return _solve_ortools(matrix, return_to_start)
        except Exception:
            pass
    return _solve_nearest_neighbour(matrix, return_to_start)
