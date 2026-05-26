"""Разрешение путей к бинарникам и помощники для subprocess.

Соблюдаем паттерны скилла media-tools: вызов только списком аргументов
(не shell=True), проверка наличия через shutil.which, явная ошибка если бинарника нет.
"""

from __future__ import annotations

import shutil
import sys


class BinaryNotFound(RuntimeError):
    """Нужный внешний бинарник не найден в системе."""

    def __init__(self, name: str, hint: str = "") -> None:
        msg = f"Не найден бинарник '{name}'."
        if hint:
            msg += f" {hint}"
        super().__init__(msg)
        self.name = name


# Кэшируем только успешный результат: неудачу (например, оборванное скачивание)
# повторно пробуем при следующем вызове, а не запоминаем на весь процесс.
_FFMPEG_PATHS: tuple[str, str] | None = None


def _static_ffmpeg_paths() -> tuple[str, str] | None:
    """Получить пути к ffmpeg/ffprobe из пакета static-ffmpeg (скачивает при первом вызове)."""
    global _FFMPEG_PATHS
    if _FFMPEG_PATHS is not None:
        return _FFMPEG_PATHS
    try:
        from static_ffmpeg import run
    except ImportError:
        return None
    try:
        _FFMPEG_PATHS = run.get_or_fetch_platform_executables_else_raise()
    except Exception:
        return None
    return _FFMPEG_PATHS


def resolve_binary(name: str) -> str:
    """Вернуть путь к бинарнику `name` или поднять BinaryNotFound.

    Логика по инструментам:
    - ffmpeg/ffprobe — сначала static-ffmpeg, затем PATH;
    - yt-dlp — console-script в PATH (включая .venv/bin), затем `python -m yt_dlp`;
    - остальные (aria2c, ...) — только PATH.
    """
    if name in ("ffmpeg", "ffprobe"):
        paths = _static_ffmpeg_paths()
        if paths is not None:
            ffmpeg, ffprobe = paths
            return ffmpeg if name == "ffmpeg" else ffprobe
        found = shutil.which(name)
        if found:
            return found
        raise BinaryNotFound(name, "Установи пакет static-ffmpeg (uv add static-ffmpeg).")

    found = shutil.which(name)
    if found:
        return found

    if name == "yt-dlp":
        # Фолбэк: модуль установлен, но console-script не на PATH.
        try:
            import yt_dlp  # noqa: F401

            return f"{sys.executable} -m yt_dlp"
        except ImportError:
            raise BinaryNotFound(name, "Установи yt-dlp (uv add yt-dlp).") from None

    hint = ""
    if name == "aria2c":
        hint = "Опционально: sudo apt install aria2 (иначе используется http-фолбэк)."
    raise BinaryNotFound(name, hint)


def have_binary(name: str) -> bool:
    """Проверить доступность бинарника, не поднимая исключение."""
    try:
        resolve_binary(name)
        return True
    except BinaryNotFound:
        return False
