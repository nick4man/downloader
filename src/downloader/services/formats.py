"""Выбор формата yt-dlp: желаемое качество → выражение для `-f`.

Бизнес-логика без I/O: превращает намерение пользователя («хочу 720p»)
в селектор формата, который понимает yt-dlp. См. паттерн в скилле media-tools:
`-f 'bestvideo[height<=?1080]+bestaudio/best'`.
"""

from __future__ import annotations


def select_format(quality: int | None = None) -> str:
    """Построить выражение для `yt-dlp -f` под желаемую высоту видео.

    Args:
        quality: желаемая максимальная высота видео в пикселях (720, 1080, ...).
            None → лучшее доступное видео+аудио без ограничения по высоте.

    Returns:
        Строку-селектор формата для `yt-dlp -f`.
    """
    if quality is None:
        return "bestvideo+bestaudio/best"
    return f"bestvideo[height<=?{quality}]+bestaudio/best"
