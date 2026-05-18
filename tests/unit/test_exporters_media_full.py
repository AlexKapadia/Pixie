"""Media exporter gap-fillers — audio, video, file paths."""

from __future__ import annotations

import shutil
import struct
import wave
from pathlib import Path

import pytest

from pixie import exporters
from pixie.exporters import ExporterError, ExporterMissingDependency


@pytest.fixture
def wav_path(tmp_path: Path) -> Path:
    p = tmp_path / "tone.wav"
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        # 0.05s of silence (400 frames @ 8kHz)
        wf.writeframes(b"\x00\x00" * 400)
    return p


@pytest.mark.asyncio
async def test_audio_original(wav_path: Path) -> None:
    payload, _ = await exporters.export(str(wav_path), "audio", format="original",
                                          output_key="a")
    assert payload == wav_path.read_bytes()


@pytest.mark.asyncio
async def test_audio_wav_via_soundfile_or_ffmpeg(wav_path: Path) -> None:
    # wav -> wav round-trip (cheapest path; uses soundfile if no ffmpeg)
    try:
        payload, _ = await exporters.export(str(wav_path), "audio", format="wav",
                                              output_key="a")
        assert payload[:4] == b"RIFF"
    except ExporterMissingDependency:
        pytest.skip("neither ffmpeg nor soundfile available for wav export")


@pytest.mark.asyncio
async def test_audio_mp3_requires_ffmpeg_when_sf_missing(
    wav_path: Path, monkeypatch,
) -> None:
    # Force ffmpeg lookup to fail by overriding which.
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ExporterMissingDependency):
        await exporters.export(str(wav_path), "audio", format="mp3", output_key="a")


@pytest.mark.asyncio
async def test_audio_inline_value_raises(tmp_path: Path) -> None:
    with pytest.raises(ExporterError):
        await exporters.export(
            "not-a-real-path", "audio", format="original", output_key="a",
        )


@pytest.mark.asyncio
async def test_video_no_ffmpeg_raises(monkeypatch, tmp_path: Path) -> None:
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"\x00" * 4)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ExporterMissingDependency):
        await exporters.export(str(fake), "video", format="mp4", output_key="v")


@pytest.mark.asyncio
async def test_video_original(tmp_path: Path) -> None:
    fake = tmp_path / "v.mp4"
    fake.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 100)
    payload, _ = await exporters.export(str(fake), "video", format="original",
                                          output_key="v")
    assert payload == fake.read_bytes()


@pytest.mark.asyncio
async def test_video_inline_raises() -> None:
    with pytest.raises(ExporterError):
        await exporters.export("nope", "video", format="original", output_key="v")
