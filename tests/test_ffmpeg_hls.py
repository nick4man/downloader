"""Интеграционный тест HLS→MP4: реальный ffmpeg на локальном потоке, без сети.

Сегментируем короткий синтетический ролик в HLS и проверяем, что наша обёртка
собирает из него валидный воспроизводимый MP4 (copy-путь, кодеки совместимы).
Пропускается, если ffmpeg недоступен (например, не скачался static-ffmpeg в CI).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from downloader.tools import ffmpeg
from downloader.tools.base import BinaryNotFound, resolve_binary

try:
    _FFMPEG: str | None = resolve_binary("ffmpeg")
except BinaryNotFound:
    _FFMPEG = None

pytestmark = pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg недоступен")


def _make_hls(dest: Path) -> Path:
    """Сгенерировать 2-сек HLS (testsrc + синус-аудио) в dest/index.m3u8."""
    subprocess.run(
        [
            _FFMPEG, "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-c:a", "aac", "-f", "hls",
            "-hls_time", "1", "-hls_list_size", "0", str(dest / "index.m3u8"),
        ],  # fmt: skip
        check=True,
    )
    return dest / "index.m3u8"


async def test_hls_to_mp4_produces_valid_mp4(tmp_path: Path) -> None:
    src = _make_hls(tmp_path)
    out = await ffmpeg.hls_to_mp4(str(src), tmp_path, "video", job_id="t")

    assert out.suffix == ".mp4"
    assert out.exists() and out.stat().st_size > 0

    info = await ffmpeg.probe(str(out))
    assert "mp4" in info["format"]["format_name"]
    assert abs(float(info["format"]["duration"]) - 2.0) < 0.5
    assert {s["codec_name"] for s in info["streams"]} == {"h264", "aac"}
