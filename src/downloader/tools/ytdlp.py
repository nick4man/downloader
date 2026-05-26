"""Обёртка над yt-dlp: метаданные, список форматов, загрузка медиа.

Соблюдаем паттерн скилла: subprocess списком аргументов, парсинг stdout,
коды возврата не глотаем. yt-dlp сам именует файл по шаблону `-o` и сам
встраивает метаданные/обложку — мы лишь оркеструем вызов и ловим прогресс.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from pathlib import Path

from downloader.core.events import ProgressCallback, noop_progress
from downloader.models import Format, MediaInfo, ProgressEvent
from downloader.tools.base import resolve_binary, terminate_if_alive

# Пример строки прогресса (с --newline):
# [download]  23.4% of   10.00MiB at    2.00MiB/s ETA 00:03
_PROGRESS = re.compile(
    r"\[download\]\s+(?P<pct>[\d.]+)%\s+of\s+~?\s*"
    r"(?P<total>[\d.]+)(?P<tu>[KMGT]i?B|B)"
    r"(?:\s+at\s+(?P<spd>[\d.]+)(?P<su>[KMGT]i?B|B)/s)?"
    r"(?:\s+ETA\s+(?P<eta>[\d:]+))?"
)
_UNITS = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30, "TiB": 1 << 40}
_UNITS.update({"KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4})


def _to_bytes(num: str, unit: str) -> int:
    return int(float(num) * _UNITS.get(unit, 1))


def _parse_eta(raw: str | None) -> float | None:
    """ETA yt-dlp вида 'MM:SS' или 'HH:MM:SS' → секунды."""
    if not raw:
        return None
    parts = [int(p) for p in raw.split(":")]
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return float(seconds)


def parse_progress(line: str, job_id: str = "") -> ProgressEvent | None:
    """Разобрать строку прогресса yt-dlp в ProgressEvent (или None)."""
    m = _PROGRESS.search(line)
    if not m:
        return None
    total = _to_bytes(m["total"], m["tu"])
    pct = float(m["pct"])
    return ProgressEvent(
        job_id=job_id,
        bytes_done=int(total * pct / 100),
        bytes_total=total,
        percent=pct,
        speed=_to_bytes(m["spd"], m["su"]) if m["spd"] else None,
        eta=_parse_eta(m["eta"]),
    )


def _base_args() -> list[str]:
    """Базовая команда yt-dlp (учитываем фолбэк 'python -m yt_dlp')."""
    return shlex.split(resolve_binary("yt-dlp"))


async def _run_json(args: list[str]) -> dict:
    """Запустить yt-dlp, ожидая JSON в stdout; поднять при ненулевом коде."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        detail = err.decode(errors="replace")[:400]
        raise RuntimeError(f"yt-dlp вышел с кодом {proc.returncode}: {detail}")
    return json.loads(out)


def _format_from_dict(d: dict) -> Format:
    return Format(
        format_id=str(d.get("format_id", "")),
        ext=d.get("ext"),
        height=d.get("height"),
        vcodec=d.get("vcodec") if d.get("vcodec") != "none" else None,
        acodec=d.get("acodec") if d.get("acodec") != "none" else None,
        filesize=d.get("filesize") or d.get("filesize_approx"),
        tbr=d.get("tbr"),
        note=d.get("format_note"),
    )


async def probe(url: str) -> MediaInfo:
    """Получить метаданные и форматы медиа через `yt-dlp -J <url>`."""
    info = await _run_json([*_base_args(), "-J", "--no-warnings", url])
    formats = [_format_from_dict(f) for f in info.get("formats", [])]
    return MediaInfo(
        url=url,
        title=info.get("title"),
        uploader=info.get("uploader"),
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail"),
        formats=formats,
        raw=info,
    )


async def list_formats(url: str) -> list[Format]:
    """Список доступных форматов (из метаданных probe)."""
    return (await probe(url)).formats


async def download(
    url: str,
    dest_dir: Path | str,
    fmt: str,
    on_progress: ProgressCallback = noop_progress,
    *,
    job_id: str = "",
) -> Path | None:
    """Скачать медиа через yt-dlp с выбранным форматом и метаданными.

    Возвращает путь к итоговому файлу (через `--print after_move:filepath`)
    или None, если путь не удалось определить.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    args = [
        *_base_args(),
        "-f",
        fmt,
        "-o",
        str(dest_dir / "%(title)s.%(ext)s"),
        "--newline",
        "--no-warnings",
        "--embed-metadata",
        "--embed-thumbnail",
        "--no-simulate",
        "--print",
        "after_move:filepath",
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    final_path: Path | None = None
    tail: list[str] = []
    try:
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            tail.append(line)
            del tail[:-20]
            event = parse_progress(line, job_id)
            if event:
                on_progress(event)
            elif not line.startswith("["):
                # Строка от --print after_move:filepath — путь итогового файла.
                candidate = Path(line)
                if candidate.exists():
                    final_path = candidate
        code = await proc.wait()
    finally:
        terminate_if_alive(proc)  # отмена/Ctrl-C — гасим дочерний yt-dlp
    if code != 0:
        raise RuntimeError(f"yt-dlp вышел с кодом {code}:\n" + "\n".join(tail[-5:]))
    return final_path
