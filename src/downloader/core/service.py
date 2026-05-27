"""Автозапуск демона как systemd user-сервиса (без root).

Пишем unit в ~/.config/systemd/user/ и управляем через `systemctl --user`.
ExecStart запускает foreground-тело демона (`daemon-serve`) — процессом
управляет systemd (автозапуск в сессии, перезапуск при падении).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from downloader.core import daemon

SERVICE_NAME = "downloader.service"
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT_PATH = UNIT_DIR / SERVICE_NAME


def unit_text() -> str:
    """Содержимое systemd-юнита (ExecStart = текущий python -m downloader)."""
    return f"""[Unit]
Description=downloader — менеджер закачек (демон)
After=network-online.target

[Service]
Type=simple
ExecStart={sys.executable} -m downloader daemon-serve
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
"""


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True, check=False
    )


def install() -> tuple[Path, str]:
    """Записать unit и включить автозапуск. Вернуть (путь, вывод systemctl)."""
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    UNIT_PATH.write_text(unit_text(), encoding="utf-8")
    _systemctl("daemon-reload")
    daemon.stop()  # погасить вручную запущенный демон, чтобы освободить порт
    res = _systemctl("enable", "--now", SERVICE_NAME)
    return UNIT_PATH, (res.stderr or res.stdout).strip()


def uninstall() -> str:
    """Отключить автозапуск и удалить unit. Вернуть вывод systemctl."""
    res = _systemctl("disable", "--now", SERVICE_NAME)
    UNIT_PATH.unlink(missing_ok=True)
    _systemctl("daemon-reload")
    return (res.stderr or res.stdout).strip()


def status() -> str:
    """is-active сервиса ('active'/'inactive'/'failed'/'unknown')."""
    return _systemctl("is-active", SERVICE_NAME).stdout.strip() or "unknown"
