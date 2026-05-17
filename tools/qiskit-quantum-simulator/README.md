# Quantum Circuit Simulator

Hand-rolled n-qubit (≤8) state-vector simulator with measurement sampling and an ASCII circuit diagram. Supports H, X, Y, Z, S, T, CX/CNOT, CZ, SWAP, RX, RY, RZ.

Specified as a `qiskit-aer` wrapper. We substituted a numpy-only implementation because aer's wheels are heavy and frequently broken on Windows + Python 3.12. The mathematics is identical for circuits up to 8 qubits.

## Install
```
cd tools/qiskit-quantum-simulator
uv sync
```

## Test
```
uv run pixie validate qiskit-quantum-simulator --summary
```
