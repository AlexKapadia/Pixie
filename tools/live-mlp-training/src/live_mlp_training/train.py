"""Pure-numpy MLP training loop. Torch is optional; the numpy path
ensures the tool validates on a fresh clone without torch installed."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

import numpy as np

from .dataset import Dataset


@dataclass(frozen=True)
class EpochResult:
    epoch: int
    train_loss: float
    val_loss: float
    train_acc: float
    val_acc: float


def _parse_hidden(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
            if n > 0:
                out.append(n)
        except ValueError:
            continue
    return out or [16]


class _MLP:
    """Numpy MLP with cross-entropy + softmax. Adam-lite optimiser."""

    def __init__(self, sizes: list[int], rng: np.random.Generator) -> None:
        self.weights: list[np.ndarray] = []
        self.biases: list[np.ndarray] = []
        for i in range(len(sizes) - 1):
            limit = np.sqrt(2.0 / sizes[i])
            self.weights.append(rng.normal(0, limit, (sizes[i], sizes[i + 1])).astype(np.float32))
            self.biases.append(np.zeros(sizes[i + 1], dtype=np.float32))

    def forward(self, x: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
        activations = [x]
        h = x
        for i, (w, b) in enumerate(zip(self.weights, self.biases, strict=True)):
            z = h @ w + b
            if i == len(self.weights) - 1:
                z = z - z.max(axis=1, keepdims=True)
                exp_z = np.exp(z)
                h = exp_z / exp_z.sum(axis=1, keepdims=True)
            else:
                h = np.maximum(z, 0)  # ReLU
            activations.append(h)
        return h, activations

    def backward(self, activations: list[np.ndarray], y: np.ndarray) -> tuple[list[np.ndarray], list[np.ndarray]]:
        # cross-entropy gradient on softmax output
        n = y.shape[0]
        grad_out = activations[-1].copy()
        grad_out[np.arange(n), y] -= 1
        grad_out /= n

        grads_w: list[np.ndarray] = [np.zeros_like(w) for w in self.weights]
        grads_b: list[np.ndarray] = [np.zeros_like(b) for b in self.biases]

        delta = grad_out
        for layer in range(len(self.weights) - 1, -1, -1):
            a_prev = activations[layer]
            grads_w[layer] = a_prev.T @ delta
            grads_b[layer] = delta.sum(axis=0)
            if layer > 0:
                a_lower = activations[layer]
                delta = (delta @ self.weights[layer].T) * (a_lower > 0)
        return grads_w, grads_b

    def update(self, grads_w: list[np.ndarray], grads_b: list[np.ndarray], lr: float) -> None:
        for i in range(len(self.weights)):
            self.weights[i] -= lr * grads_w[i]
            self.biases[i] -= lr * grads_b[i]


def _loss_and_acc(probs: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    n = y.shape[0]
    eps = 1e-9
    loss = float(-np.log(probs[np.arange(n), y] + eps).mean())
    acc = float((probs.argmax(axis=1) == y).mean())
    return loss, acc


async def train(
    dataset: Dataset,
    hidden_sizes: str,
    epochs: int,
    learning_rate: float,
    batch_size: int,
    seed: int,
) -> AsyncIterator[EpochResult]:
    rng = np.random.default_rng(seed)
    sizes = [dataset.n_features, *_parse_hidden(hidden_sizes), dataset.n_classes]
    model = _MLP(sizes, rng)

    n_train = len(dataset.features_train)
    indices = np.arange(n_train)

    for epoch in range(1, max(1, epochs) + 1):
        rng.shuffle(indices)
        batch_losses: list[float] = []
        batch_accs: list[float] = []
        for start in range(0, n_train, batch_size):
            stop = start + batch_size
            batch_idx = indices[start:stop]
            xb = dataset.features_train[batch_idx]
            yb = dataset.labels_train[batch_idx]
            probs, activations = model.forward(xb)
            loss, acc = _loss_and_acc(probs, yb)
            batch_losses.append(loss)
            batch_accs.append(acc)
            grads_w, grads_b = model.backward(activations, yb)
            model.update(grads_w, grads_b, learning_rate)
        train_loss = float(np.mean(batch_losses))
        train_acc = float(np.mean(batch_accs))
        # validation
        val_probs, _ = model.forward(dataset.features_val)
        val_loss, val_acc = _loss_and_acc(val_probs, dataset.labels_val)
        yield EpochResult(
            epoch=epoch,
            train_loss=round(train_loss, 6),
            val_loss=round(val_loss, 6),
            train_acc=round(train_acc, 6),
            val_acc=round(val_acc, 6),
        )
        # yield control so the SSE loop can flush
        await asyncio.sleep(0)
