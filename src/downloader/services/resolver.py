"""Классификация ссылок и выбор загрузчика.

Эвристика (без сетевых запросов):
- `.m3u8` → HLS (ffmpeg);
- известное файловое расширение → DIRECT (aria2/http);
- хост из медиа-allowlist → MEDIA (yt-dlp);
- иначе → DIRECT (безопасный дефолт; прямые ссылки без расширения работают).
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

# Хосты, которые качаем через yt-dlp (подстрока хоста). Список легко расширять.
_MEDIA_HOSTS = (
    "youtube.com", "youtu.be", "vimeo.com", "twitch.tv", "tiktok.com",
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "soundcloud.com", "dailymotion.com", "rutube.ru", "vk.com",
)  # fmt: skip


def classify(url: str) -> DownloadKind:
    """Определить тип ссылки."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".m3u8"):
        return DownloadKind.HLS
    if PurePosixPath(path).suffix in _DIRECT_EXTS:
        return DownloadKind.DIRECT
    host = parsed.hostname or ""
    if any(h in host for h in _MEDIA_HOSTS):
        return DownloadKind.MEDIA
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
