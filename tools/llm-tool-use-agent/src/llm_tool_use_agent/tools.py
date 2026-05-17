"""Built-in tools. Calculator uses safe AST evaluation; web_search is a local stub."""
from __future__ import annotations

import ast
import operator
from typing import Any

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.operand))
    raise ValueError("unsupported expression")


def calculator(expression: str) -> str:
    tree = ast.parse(expression, mode="eval")
    return str(_evaluate(tree.body))


_SEARCH_INDEX: dict[str, str] = {
    "pixie": "Pixie is a local-first dashboard for personal tools and models, built on FastAPI + htmx.",
    "lorenz": "The Lorenz attractor is a chaotic 3-D dynamical system discovered by Edward Lorenz in 1963.",
    "monte carlo": "Monte Carlo methods estimate quantities by repeated random sampling.",
    "fastapi": "FastAPI is a modern Python web framework built on Starlette and Pydantic.",
}


def web_search(query: str) -> str:
    needle = query.lower()
    for key, summary in _SEARCH_INDEX.items():
        if key in needle:
            return summary
    return f"No reliable results found for: {query}"


REGISTRY: dict[str, dict[str, Any]] = {
    "calculator": {
        "schema": {
            "name": "calculator",
            "description": "Evaluate a basic arithmetic expression (+, -, *, /, **, %).",
            "input_schema": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
        "fn": lambda args: calculator(args["expression"]),
    },
    "web_search": {
        "schema": {
            "name": "web_search",
            "description": "Look up a short summary for a query (sandboxed in-memory index).",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        "fn": lambda args: web_search(args["query"]),
    },
}
