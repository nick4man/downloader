"""Создание задачи из ссылки — общая логика для CLI и демона."""

from __future__ import annotations

from pathlib import Path

from downloader.config import Config
from downloader.models import DownloadJob, DownloadKind
from downloader.services.formats import select_format
from downloader.services.resolver import classify


def build_job(
    url: str,
    config: Config,
    *,
    dest_dir: str | None = None,
    quality: int | None = None,
    audio: bool = False,
) -> DownloadJob:
    """Собрать DownloadJob: классифицировать ссылку, выбрать -f (видео) / режим аудио."""
    dest = dest_dir or config.download_dir
    kind = classify(url)
    # Для видео-медиа фиксируем -f по качеству; для аудио формат не нужен (yt-dlp -x).
    fmt = None
    if kind is DownloadKind.MEDIA and not audio:
        fmt = select_format(quality or config.default_quality)
    return DownloadJob(
        url=url, dest_dir=str(Path(dest).expanduser()), kind=kind, fmt=fmt, audio=audio
    )
