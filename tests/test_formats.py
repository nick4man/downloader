"""Тесты выбора формата yt-dlp по качеству."""

from __future__ import annotations

from downloader.services.formats import select_format


def test_quality_limits_height() -> None:
    # Заданное качество → мягкое ограничение высоты + склейка с аудио + фолбэк.
    assert select_format(720) == "bestvideo[height<=?720]+bestaudio/best"
    assert select_format(1080) == "bestvideo[height<=?1080]+bestaudio/best"


def test_none_is_best_available() -> None:
    # Без ограничения — лучшее доступное.
    assert select_format(None) == "bestvideo+bestaudio/best"


def test_default_is_none() -> None:
    # Дефолтный вызов не падает и не ограничивает высоту.
    assert "height" not in select_format()
