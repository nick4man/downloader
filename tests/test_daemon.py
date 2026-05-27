"""Тесты управления фоновым демоном (без запуска реального процесса)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from downloader.core import daemon


@pytest.fixture
def pidfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Подменить путь pid-файла на временный."""
    p = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon, "PID_PATH", p)
    return p


def test_is_running_no_pidfile(pidfile: Path) -> None:
    assert daemon.is_running() is None


def test_is_running_live_pid(pidfile: Path) -> None:
    # Наш собственный процесс гарантированно жив.
    pidfile.write_text(str(os.getpid()))
    assert daemon.is_running() == os.getpid()


def test_is_running_stale_pid_cleaned(pidfile: Path) -> None:
    # Заведомо несуществующий PID → None и файл удалён.
    pidfile.write_text("999999")
    assert daemon.is_running() is None
    assert not pidfile.exists()


def test_is_running_garbage_pidfile(pidfile: Path) -> None:
    pidfile.write_text("не число")
    assert daemon.is_running() is None
    assert not pidfile.exists()


def test_stop_when_not_running(pidfile: Path) -> None:
    assert daemon.stop() is False
