"""Edge-list parsing + Dijkstra, max-flow, and community-detection drivers."""
from __future__ import annotations

from typing import Any

import networkx as nx


def parse_edges(text: str) -> nx.Graph:
    graph = nx.Graph()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            edge_part, weight_part = line.split(":", 1)
            weight = float(weight_part.strip())
        else:
            edge_part, weight = line, 1.0
        nodes = [n.strip() for n in edge_part.split("-")]
        if len(nodes) != 2 or not all(nodes):
            raise ValueError(f"cannot parse edge {line!r}; expected 'a-b:weight'")
        graph.add_edge(nodes[0], nodes[1], weight=weight, capacity=weight)
    return graph


def layout(graph: nx.Graph) -> dict[str, tuple[float, float]]:
    if len(graph) == 0:
        return {}
    return {n: (float(x), float(y)) for n, (x, y) in nx.spring_layout(graph, seed=42).items()}


def run_dijkstra(graph: nx.Graph, source: str) -> dict[str, Any]:
    distances, paths = nx.single_source_dijkstra(graph, source)
    rows = [
        {"node": node, "distance": round(float(d), 4), "path": " → ".join(paths[node])}
        for node, d in sorted(distances.items(), key=lambda kv: kv[1])
    ]
    highlighted_edges = set()
    for node, path in paths.items():
        for i in range(len(path) - 1):
            highlighted_edges.add(tuple(sorted([path[i], path[i + 1]])))
    summary = {
        "source": source,
        "nodes_reached": len(distances),
        "farthest_node": max(distances, key=distances.get),
        "farthest_distance": round(float(max(distances.values())), 4),
    }
    return {"rows": rows, "highlighted_edges": highlighted_edges, "summary": summary}


def run_max_flow(graph: nx.Graph, source: str, sink: str) -> dict[str, Any]:
    directed = graph.to_directed()
    flow_value, flow_dict = nx.maximum_flow(directed, source, sink, capacity="capacity")
    rows: list[dict[str, Any]] = []
    highlighted_edges: set[tuple[str, str]] = set()
    for u, dests in flow_dict.items():
        for v, f in dests.items():
            if f > 0:
                rows.append({"from": u, "to": v, "flow": round(float(f), 4)})
                highlighted_edges.add(tuple(sorted([u, v])))
    summary = {
        "source": source,
        "sink": sink,
        "max_flow": round(float(flow_value), 4),
        "saturated_edges": len(highlighted_edges),
    }
    return {"rows": rows, "highlighted_edges": highlighted_edges, "summary": summary}


def run_communities(graph: nx.Graph) -> dict[str, Any]:
    communities = list(nx.community.greedy_modularity_communities(graph, weight="weight"))
    rows: list[dict[str, Any]] = []
    membership: dict[str, int] = {}
    for idx, community in enumerate(communities):
        for node in community:
            membership[node] = idx
            rows.append({"node": node, "community": idx})
    rows.sort(key=lambda r: (r["community"], r["node"]))
    summary = {
        "communities_found": len(communities),
        "largest_community_size": max(len(c) for c in communities) if communities else 0,
        "modularity": round(float(nx.community.modularity(graph, communities, weight="weight")), 4),
    }
    return {"rows": rows, "membership": membership, "summary": summary}
