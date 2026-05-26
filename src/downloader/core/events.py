"""Типы событий прогресса и общий контракт загрузчиков."""

from __future__ import annotations

from collections.abc import Callable

from downloader.models import ProgressEvent

# Колбэк, который воркер передаёт загрузчику для отчёта о прогрессе.
ProgressCallback = Callable[[ProgressEvent], None]


def noop_progress(_: ProgressEvent) -> None:
    """Заглушка прогресса (когда отчёт не нужен)."""
