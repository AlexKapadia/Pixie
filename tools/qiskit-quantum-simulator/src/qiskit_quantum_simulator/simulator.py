"""Hand-rolled n-qubit (≤8) state-vector simulator.

Substituted for `qiskit-aer` because the aer wheels are heavy and intermittently
broken on Windows + Python 3.12. Numpy-only, exact, fast for ≤8 qubits.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MAX_QUBITS = 8


@dataclass
class ParsedCircuit:
    n_qubits: int
    gates: list[tuple[str, list[int], list[float]]]


SINGLE_QUBIT = {
    "H": np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    "S": np.array([[1, 0], [0, 1j]], dtype=complex),
    "T": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
}


def parse(text: str) -> ParsedCircuit:
    lines = [line.strip() for line in text.splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]
    n_qubits = 3
    gates: list[tuple[str, list[int], list[float]]] = []
    for line in lines:
        parts = line.split()
        head = parts[0].upper()
        if head == "QUBITS":
            n_qubits = int(parts[1])
            if n_qubits < 1 or n_qubits > MAX_QUBITS:
                raise ValueError(f"qubits must be between 1 and {MAX_QUBITS}")
            continue
        if head in SINGLE_QUBIT:
            gates.append((head, [int(parts[1])], []))
        elif head in {"CX", "CNOT"}:
            gates.append(("CX", [int(parts[1]), int(parts[2])], []))
        elif head == "CZ":
            gates.append(("CZ", [int(parts[1]), int(parts[2])], []))
        elif head == "SWAP":
            gates.append(("SWAP", [int(parts[1]), int(parts[2])], []))
        elif head in {"RX", "RY", "RZ"}:
            gates.append((head, [int(parts[1])], [float(parts[2])]))
        else:
            raise ValueError(f"unknown gate {head!r}")
    for _, qubits, _ in gates:
        for q in qubits:
            if q < 0 or q >= n_qubits:
                raise ValueError(f"qubit {q} out of range for {n_qubits}-qubit circuit")
    return ParsedCircuit(n_qubits=n_qubits, gates=gates)


def _apply_single(state: np.ndarray, gate: np.ndarray, qubit: int, n: int) -> np.ndarray:
    state = state.reshape([2] * n)
    state = np.tensordot(gate, state, axes=([1], [qubit]))
    # tensordot puts the new axis at position 0; move it back to `qubit`.
    state = np.moveaxis(state, 0, qubit)
    return state.reshape(-1)


def _apply_cnot(state: np.ndarray, control: int, target: int, n: int) -> np.ndarray:
    state = state.reshape([2] * n).copy()
    sl_ctrl_one = [slice(None)] * n
    sl_ctrl_one[control] = 1
    block = state[tuple(sl_ctrl_one)]
    # Apply X to target within that block.
    block = np.flip(block, axis=target if target < control else target - 1)
    state[tuple(sl_ctrl_one)] = block
    return state.reshape(-1)


def _apply_cz(state: np.ndarray, q1: int, q2: int, n: int) -> np.ndarray:
    state = state.reshape([2] * n).copy()
    sl = [slice(None)] * n
    sl[q1] = 1
    sl[q2] = 1
    state[tuple(sl)] *= -1
    return state.reshape(-1)


def _apply_swap(state: np.ndarray, q1: int, q2: int, n: int) -> np.ndarray:
    if q1 == q2:
        return state
    state = state.reshape([2] * n)
    state = np.swapaxes(state, q1, q2)
    return state.reshape(-1)


def _rotation(name: str, theta: float) -> np.ndarray:
    c, s = np.cos(theta / 2.0), np.sin(theta / 2.0)
    if name == "RX":
        return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)
    if name == "RY":
        return np.array([[c, -s], [s, c]], dtype=complex)
    if name == "RZ":
        return np.array([[np.exp(-1j * theta / 2.0), 0],
                         [0, np.exp(1j * theta / 2.0)]], dtype=complex)
    raise ValueError(name)


def simulate(circuit: ParsedCircuit) -> np.ndarray:
    n = circuit.n_qubits
    state = np.zeros(2 ** n, dtype=complex)
    state[0] = 1.0
    for name, qubits, params in circuit.gates:
        if name in SINGLE_QUBIT:
            state = _apply_single(state, SINGLE_QUBIT[name], qubits[0], n)
        elif name == "CX":
            state = _apply_cnot(state, qubits[0], qubits[1], n)
        elif name == "CZ":
            state = _apply_cz(state, qubits[0], qubits[1], n)
        elif name == "SWAP":
            state = _apply_swap(state, qubits[0], qubits[1], n)
        elif name in {"RX", "RY", "RZ"}:
            state = _apply_single(state, _rotation(name, params[0]), qubits[0], n)
    return state


def sample(state: np.ndarray, n: int, shots: int, seed: int = 0) -> dict[str, int]:
    probs = np.abs(state) ** 2
    probs = probs / probs.sum()
    rng = np.random.default_rng(seed)
    samples = rng.choice(len(probs), size=shots, p=probs)
    counts: dict[str, int] = {}
    for s in samples:
        # Most-significant qubit first (qiskit convention reversed for readability).
        bits = format(int(s), f"0{n}b")
        counts[bits] = counts.get(bits, 0) + 1
    return dict(sorted(counts.items()))


def ascii_diagram(circuit: ParsedCircuit) -> str:
    n = circuit.n_qubits
    rows = [[f"q{i}: |0⟩ "] for i in range(n)]
    for name, qubits, params in circuit.gates:
        if name in SINGLE_QUBIT or name in {"RX", "RY", "RZ"}:
            label = name if name in SINGLE_QUBIT else f"{name}({params[0]:.2f})"
            for i in range(n):
                rows[i].append(f"--[{label.center(max(len(label), 3))}]--" if i == qubits[0] else "-" * (len(label) + 6))
        elif name in {"CX", "CZ"}:
            ctrl, targ = qubits
            label_t = "X" if name == "CX" else "Z"
            for i in range(n):
                if i == ctrl:
                    rows[i].append("-----•-----")
                elif i == targ:
                    rows[i].append(f"---[ {label_t} ]---")
                else:
                    rows[i].append("-" * 11)
        elif name == "SWAP":
            for i in range(n):
                if i in qubits:
                    rows[i].append("-----X-----")
                else:
                    rows[i].append("-" * 11)
    return "\n".join("".join(r) for r in rows)
