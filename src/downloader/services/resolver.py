"""Классификация ссылок и выбор загрузчика.

Эвристика (без сетевых запросов):
- `.m3u8` → HLS (ffmpeg);
- известное файловое расширение → DIRECT (aria2/http);
- иначе → MEDIA (yt-dlp): для менеджера видео логичнее доверять yt-dlp с его
  generic- и сотнями сайтовых экстракторов, чем считать страницу прямым файлом.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse

from downloader.models import DownloadKind, Engine
from downloader.tools.base import have_binary

# Расширения, означающие прямой файл (архивы, образы, документы, медиа-контейнеры).
_DIRECT_EXTS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz",
    ".iso", ".img", ".dmg", ".exe", ".msi", ".deb", ".rpm", ".apk", ".appimage",
    ".pdf", ".epub", ".mobi",
    ".mp3", ".flac", ".wav", ".ogg", ".m4a",
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv",
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".bin", ".dat",
}  # fmt: skip


def classify(url: str) -> DownloadKind:
    """Определить тип ссылки."""
    path = urlparse(url).path.lower()
    if path.endswith(".m3u8"):
        return DownloadKind.HLS
    if PurePosixPath(path).suffix in _DIRECT_EXTS:
        return DownloadKind.DIRECT
    # Прямые файлы отсеяны по расширению выше — остальное отдаём yt-dlp.
    return DownloadKind.MEDIA


def choose_engine(kind: DownloadKind) -> Engine:
    """Выбрать движок под тип ссылки.

    Для прямых файлов предпочитаем aria2 (сегментная докачка), иначе http-фолбэк.
    """
    if kind is DownloadKind.HLS:
        return Engine.FFMPEG
    if kind is DownloadKind.MEDIA:
        return Engine.YTDLP
    return Engine.ARIA2 if have_binary("aria2c") else Engine.HTTP
