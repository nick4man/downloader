"""Классификация ссылок и выбор загрузчика.

Phase 1: распознаём только прямые файлы (direct) и выбираем движок
aria2 (если доступен) или http-фолбэк. Распознавание media/HLS — в Phase 2/3.
"""

from __future__ import annotations

from urllib.parse import urlparse

from downloader.models import DownloadKind, Engine
from downloader.tools.base import have_binary


def classify(url: str) -> DownloadKind:
    """Определить тип ссылки."""
    path = urlparse(url).path.lower()
    if path.endswith(".m3u8"):
        return DownloadKind.HLS
    # Эвристика media/direct уточнится в Phase 2 (через yt-dlp probe).
    return DownloadKind.DIRECT


def choose_engine(kind: DownloadKind) -> Engine:
    """Выбрать движок под тип ссылки.

    Для прямых файлов предпочитаем aria2 (сегментная докачка), иначе http-фолбэк.
    """
    if kind is DownloadKind.HLS:
        return Engine.FFMPEG
    if kind is DownloadKind.MEDIA:
        return Engine.YTDLP
    return Engine.ARIA2 if have_binary("aria2c") else Engine.HTTP
