"""Тест генерации systemd-юнита."""

from __future__ import annotations

import sys

from downloader.core import service


def test_unit_text() -> None:
    t = service.unit_text()
    assert "[Service]" in t and "[Install]" in t
    assert "daemon-serve" in t  # запускаем foreground-тело демона
    assert sys.executable in t  # тот же python (venv)
    assert "WantedBy=default.target" in t  # user-сервис
    assert "Restart=on-failure" in t
