"""Тесты классификации ссылок и выбора движка."""

from __future__ import annotations

from downloader.models import DownloadKind, Engine
from downloader.services.resolver import choose_engine, classify


def test_classify() -> None:
    assert classify("https://e.com/stream/index.m3u8") is DownloadKind.HLS
    assert classify("https://e.com/file.zip") is DownloadKind.DIRECT


def test_classify_media_hosts() -> None:
    assert classify("https://www.youtube.com/watch?v=abc") is DownloadKind.MEDIA
    assert classify("https://youtu.be/abc") is DownloadKind.MEDIA
    assert classify("https://vimeo.com/12345") is DownloadKind.MEDIA


def test_classify_defaults_to_direct() -> None:
    # Ссылка без расширения и не с медиа-хоста — безопасный дефолт DIRECT.
    assert classify("https://speed.cloudflare.com/__down?bytes=8000000") is DownloadKind.DIRECT
    # Прямой медиа-файл по расширению — тоже DIRECT (качаем aria2, не yt-dlp).
    assert classify("https://cdn.example.com/video.mp4") is DownloadKind.DIRECT


def test_choose_engine_special() -> None:
    assert choose_engine(DownloadKind.HLS) is Engine.FFMPEG
    assert choose_engine(DownloadKind.MEDIA) is Engine.YTDLP


def test_choose_engine_direct() -> None:
    # aria2 если есть, иначе http-фолбэк — оба валидны.
    assert choose_engine(DownloadKind.DIRECT) in (Engine.ARIA2, Engine.HTTP)
