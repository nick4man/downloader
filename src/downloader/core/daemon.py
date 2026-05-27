"""Фоновый демон: крутит движок над общей SQLite-очередью.

Сокет/RPC не нужен — состояние и очередь живут в SQLite: CLI-команды пишут
задачи в БД, демон их подхватывает. Управление процессом — через pid-файл.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time

from downloader.config import DATA_DIR, load_config

PID_PATH = DATA_DIR / "daemon.pid"
LOG_PATH = DATA_DIR / "daemon.log"


def is_running() -> int | None:
    """PID живого демона или None. Попутно чистит устаревший pid-файл."""
    if not PID_PATH.exists():
        return None
    try:
        pid = int(PID_PATH.read_text().strip())
    except ValueError:
        PID_PATH.unlink(missing_ok=True)
        return None
    try:
        os.kill(pid, 0)  # сигнал 0 — проверка существования процесса
    except ProcessLookupError:
        PID_PATH.unlink(missing_ok=True)  # устаревший файл
        return None
    except PermissionError:
        return pid  # процесс есть, просто не наш — считаем живым
    return pid


def start() -> int:
    """Запустить демон отдельным сеансом. Вернуть PID (или уже существующий)."""
    existing = is_running()
    if existing:
        return existing
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_PATH.open("a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "downloader", "daemon-serve"],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # setsid: отвязка от управляющего терминала
    )
    # Дочерний процесс сам пишет pid-файл при старте — ждём его появления.
    for _ in range(50):
        if is_running():
            break
        time.sleep(0.1)
    return proc.pid


def restart() -> int:
    """Полный перезапуск демона (новый код, миграции, размер пула). Вернуть PID."""
    stop()
    return start()


def stop(timeout: float = 10.0) -> bool:
    """Послать демону SIGTERM и дождаться выхода. False, если он не работал."""
    pid = is_running()
    if not pid:
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running() is None:
            return True
        time.sleep(0.1)
    # Не остановился по-хорошему — добиваем и подчищаем pid-файл.
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    PID_PATH.unlink(missing_ok=True)
    return True


async def serve() -> None:
    """Тело фонового демона: записать pid, поднять uvicorn с FastAPI, убрать pid.

    uvicorn сам ставит обработчики SIGTERM/SIGINT и делает graceful shutdown,
    при котором lifespan останавливает планировщик и закрывает БД.
    """
    import uvicorn

    from downloader.core.api import app

    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))
    config = load_config()
    server = uvicorn.Server(
        uvicorn.Config(app, host=config.host, port=config.port, log_config=None)
    )
    try:
        await server.serve()
    finally:
        PID_PATH.unlink(missing_ok=True)
