"""Generate the tiny binary fixtures used by the Phase 10d matrix.

Run once: ``uv run python tests/e2e/fixtures/_gen_fixtures.py``.

We commit the generated fixtures so the matrix is hermetic. This
generator script is kept alongside them as documentation and to allow
re-creation if the format ever drifts.
"""

from __future__ import annotations

import csv
import math
import struct
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _gen_csv_basic() -> None:
    # 100 rows: timestamp, value (sin wave), category
    rows = []
    for i in range(100):
        rows.append({
            "timestamp": f"2024-01-{1 + (i % 28):02d}T00:00:00",
            "value": round(50 + 10 * math.sin(i / 6.0), 4),
            "category": ["A", "B", "C"][i % 3],
        })
    with (HERE / "tiny.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "value", "category"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _gen_csv_series() -> None:
    # date + value for time-series tools
    with (HERE / "tiny_series.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "value"])
        w.writeheader()
        for i in range(120):
            day = 1 + (i % 28)
            month = 1 + (i // 28)
            w.writerow({
                "date": f"2024-{month:02d}-{day:02d}",
                "value": round(100 + 5 * math.sin(i / 7.0) + i * 0.2, 3),
            })


def _gen_csv_ohlc() -> None:
    # OHLC for backtest-engine
    with (HERE / "tiny_ohlc.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["date", "open", "high", "low", "close", "volume"]
        )
        w.writeheader()
        price = 100.0
        for i in range(120):
            day = 1 + (i % 28)
            month = 1 + (i // 28)
            drift = math.sin(i / 8.0) * 2
            o = price
            c = price + drift
            h = max(o, c) + 0.5
            lo = min(o, c) - 0.5
            w.writerow({
                "date": f"2024-{month:02d}-{day:02d}",
                "open": round(o, 3), "high": round(h, 3),
                "low": round(lo, 3), "close": round(c, 3),
                "volume": 1000 + i * 10,
            })
            price = c


def _gen_csv_returns() -> None:
    # returns matrix for markowitz-portfolio
    with (HERE / "tiny_returns.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "AAA", "BBB", "CCC"])
        w.writeheader()
        for i in range(120):
            day = 1 + (i % 28)
            month = 1 + (i // 28)
            w.writerow({
                "date": f"2024-{month:02d}-{day:02d}",
                "AAA": round(0.001 * math.sin(i / 5.0), 5),
                "BBB": round(0.002 * math.cos(i / 6.0), 5),
                "CCC": round(0.0015 * math.sin(i / 4.0 + 1.5), 5),
            })


def _gen_csv_target() -> None:
    # csv with a binary target for live-mlp-training
    with (HERE / "tiny_target.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["x1", "x2", "x3", "target"])
        w.writeheader()
        for i in range(100):
            x1 = (i % 10) / 10.0
            x2 = ((i * 3) % 7) / 7.0
            x3 = ((i * 5) % 9) / 9.0
            target = 1 if (x1 + x2 + x3) > 1.2 else 0
            w.writerow({"x1": x1, "x2": x2, "x3": x3, "target": target})


def _gen_csv_text() -> None:
    # csv with text + date columns for bertopic / sentiment / etc
    texts = [
        "the product is great and i love it",
        "shipping was slow but worth the wait",
        "absolutely terrible customer service today",
        "neutral statement about a normal day",
        "excellent quality and lovely packaging",
    ]
    with (HERE / "tiny_text.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "text"])
        w.writeheader()
        for i in range(80):
            day = 1 + (i % 28)
            month = 1 + (i // 28)
            w.writerow({
                "date": f"2024-{month:02d}-{day:02d}",
                "text": texts[i % len(texts)],
            })


def _gen_csv_kde() -> None:
    # lon, lat points for geospatial-kde-heatmap
    with (HERE / "tiny_points.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["lon", "lat"])
        w.writeheader()
        for i in range(60):
            w.writerow({
                "lon": round(-0.1 + 0.001 * (i % 12), 5),
                "lat": round(51.5 + 0.001 * (i % 9), 5),
            })


def _gen_csv_causal() -> None:
    # treatment / outcome / confounder for dowhy
    with (HERE / "tiny_causal.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["treatment", "outcome", "age"])
        w.writeheader()
        for i in range(120):
            t = i % 2
            age = 20 + (i % 50)
            y = 5.0 + 2.0 * t + 0.1 * age + (i % 7) * 0.05
            w.writerow({"treatment": t, "outcome": round(y, 3), "age": age})


def _gen_csv_survival() -> None:
    # time / event for kaplan-meier-cox
    with (HERE / "tiny_survival.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "event"])
        w.writeheader()
        for i in range(80):
            t = 5 + (i % 50)
            e = 1 if (i % 3) != 0 else 0
            w.writerow({"time": t, "event": e})


def _gen_csv_anomaly() -> None:
    # timestamp + value series with planted outliers
    with (HERE / "tiny_anomaly.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "value"])
        w.writeheader()
        for i in range(120):
            day = 1 + (i % 28)
            month = 1 + (i // 28)
            base = 50 + 5 * math.sin(i / 8.0)
            if i in {25, 60, 95}:
                base += 50.0  # outliers
            w.writerow({
                "timestamp": f"2024-{month:02d}-{day:02d}T00:00:00",
                "value": round(base, 3),
            })


def _gen_png() -> None:
    """Minimal valid 16x16 RGB PNG (red square) via raw bytes."""
    import zlib

    width, height = 16, 16
    raw = b""
    for y in range(height):
        raw += b"\x00"  # filter byte
        for _ in range(width):
            raw += b"\xff\x40\x40"  # R, G, B
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw)
    png_bytes = signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    (HERE / "tiny.png").write_bytes(png_bytes)
    # second copy used as a style image
    (HERE / "tiny_style.png").write_bytes(png_bytes)


def _gen_wav() -> None:
    """0.5s of 440Hz mono 16-bit PCM."""
    sample_rate = 8000
    duration = 0.5
    n = int(sample_rate * duration)
    with wave.open(str(HERE / "tiny.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n):
            sample = int(0.3 * 32767 * math.sin(2 * math.pi * 440 * i / sample_rate))
            frames += struct.pack("<h", sample)
        w.writeframes(bytes(frames))


def _gen_text_doc() -> None:
    """Plain text doc for RAG."""
    (HERE / "tiny_doc.txt").write_text(
        "Pixie is a local-first dashboard for running tools. "
        "It binds to loopback only. It uses FastAPI and htmx. "
        "Every tool runs as its own subprocess with its own venv. "
        "The validator runs eleven checks before declaring a tool valid.",
        encoding="utf-8",
    )


def main() -> None:
    _gen_csv_basic()
    _gen_csv_series()
    _gen_csv_ohlc()
    _gen_csv_returns()
    _gen_csv_target()
    _gen_csv_text()
    _gen_csv_kde()
    _gen_csv_causal()
    _gen_csv_survival()
    _gen_csv_anomaly()
    _gen_png()
    _gen_wav()
    _gen_text_doc()
    print("generated fixtures in", HERE)


if __name__ == "__main__":
    main()
