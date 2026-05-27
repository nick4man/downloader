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
) -> DownloadJob:
    """Собрать DownloadJob: классифицировать ссылку и для медиа выбрать -f."""
    dest = dest_dir or config.download_dir
    kind = classify(url)
    fmt = select_format(quality or config.default_quality) if kind is DownloadKind.MEDIA else None
    return DownloadJob(url=url, dest_dir=str(Path(dest).expanduser()), kind=kind, fmt=fmt)
