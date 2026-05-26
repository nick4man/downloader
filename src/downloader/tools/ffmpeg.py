"""Обёртка над ffmpeg/ffprobe: HLS → MP4.

Соблюдаем паттерн скилла: subprocess списком аргументов, парсинг прогресса,
коды возврата не глотаем. Стратегия: сначала пробуем скопировать потоки
без перекодирования (`-c copy`, быстро и без потери качества), и только
если контейнер MP4 не принимает кодеки — перекодируем.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from downloader.core.events import ProgressCallback, noop_progress
from downloader.models import ProgressEvent
from downloader.tools.base import resolve_binary


async def probe(source: str) -> dict:
    """Метаданные источника через `ffprobe -show_format -show_streams` (JSON)."""
    ffprobe = resolve_binary("ffprobe")
    args = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        source,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        detail = err.decode(errors="replace")[:300]
        raise RuntimeError(f"ffprobe вышел с кодом {proc.returncode}: {detail}")
    return json.loads(out)


async def _duration(source: str) -> float | None:
    """Длительность источника в секундах (для прогресса); None если неизвестна."""
    try:
        info = await probe(source)
    except Exception:
        return None
    raw = info.get("format", {}).get("duration")
    return float(raw) if raw else None


def _copy_args(ffmpeg: str, source: str, out: Path) -> list[str]:
    """Аргументы для сохранения без перекодирования (быстро, без потери качества)."""
    return [
        ffmpeg, "-y", "-loglevel", "error",
        "-i", source,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",  # ADTS→ASC: AAC из HLS совместим с MP4
        "-progress", "pipe:1", "-nostats",
        str(out),
    ]  # fmt: skip


def _transcode_args(ffmpeg: str, source: str, out: Path) -> list[str]:
    """Аргументы для перекодирования (фолбэк, если -c copy не подходит)."""
    return [
        ffmpeg, "-y", "-loglevel", "error",
        "-i", source,
        "-c:v", "libx264", "-c:a", "aac",
        "-progress", "pipe:1", "-nostats",
        str(out),
    ]  # fmt: skip


async def _run(
    args: list[str], total: float | None, on_progress: ProgressCallback, job_id: str
) -> None:
    """Запустить ffmpeg, парся `-progress` из stdout; поднять при ненулевом коде."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        # ffmpeg -progress отдаёт строки key=value; нас интересует out_time_us.
        if line.startswith("out_time_us=") and total:
            us = line.split("=", 1)[1]
            if us.isdigit():
                done = int(us) / 1_000_000  # секунды
                on_progress(
                    ProgressEvent(
                        job_id=job_id,
                        bytes_done=int(done),
                        bytes_total=int(total),
                        percent=min(100.0, 100 * done / total),
                    )
                )
    code = await proc.wait()
    if code != 0:
        err = (await proc.stderr.read()).decode(errors="replace")[:400] if proc.stderr else ""
        raise RuntimeError(f"ffmpeg вышел с кодом {code}: {err}")


async def hls_to_mp4(
    source: str,
    dest_dir: Path | str,
    filename: str,
    on_progress: ProgressCallback = noop_progress,
    *,
    job_id: str = "",
) -> Path:
    """Сохранить HLS-поток (m3u8) в MP4. Вернуть путь к результату."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = (dest_dir / filename).with_suffix(".mp4")
    ffmpeg = resolve_binary("ffmpeg")
    total = await _duration(source)

    # Сначала без перекодирования; если кодеки несовместимы с MP4 — перекодируем.
    try:
        await _run(_copy_args(ffmpeg, source, out), total, on_progress, job_id)
    except RuntimeError:
        await _run(_transcode_args(ffmpeg, source, out), total, on_progress, job_id)
    return out
