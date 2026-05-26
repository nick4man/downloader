"""Интеграционный тест докачки http_downloader на локальном Range-сервере.

Сеть из теста исключена: поднимаем свой HTTP-сервер с поддержкой Range,
симулируем прерванную закачку (готовый .part) и проверяем возобновление.
"""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from downloader.tools import http_downloader

# Детерминированный 1 МБ контента (псевдослучайный, но воспроизводимый).
BLOB = bytes((i * 7 + 3) % 256 for i in range(1_000_000))


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    """Отдаёт BLOB, поддерживая `Range: bytes=N-`; пишет смещения запросов."""

    # Стартовые смещения всех полученных GET-запросов (для проверки докачки).
    served_ranges: list[int] = []

    def log_message(self, *args: object) -> None:  # глушим лог сервера
        pass

    def do_GET(self) -> None:  # noqa: N802 — имя из BaseHTTPRequestHandler
        rng = self.headers.get("Range")
        start = int(rng.removeprefix("bytes=").split("-")[0]) if rng else 0
        type(self).served_ranges.append(start)

        body = BLOB[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(body)))
        if start:
            self.send_header("Content-Range", f"bytes {start}-{len(BLOB) - 1}/{len(BLOB)}")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def range_server():
    """Локальный Range-сервер на эфемерном порту; возвращает URL файла."""
    _RangeHandler.served_ranges = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _RangeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/file.bin"
    finally:
        srv.shutdown()


async def test_resume_appends_remaining(range_server: str, tmp_path: Path) -> None:
    # Симулируем прерванную закачку: первая треть уже лежит в .part.
    prefix = 300_000
    (tmp_path / "file.bin.part").write_bytes(BLOB[:prefix])

    result = await http_downloader.download(range_server, tmp_path, "file.bin", job_id="t")
    data = Path(result).read_bytes()

    # (1) Целостность: файл докачан целиком и совпадает с эталоном побайтово.
    assert data == BLOB
    # (2) Возобновление: ровно один запрос к серверу, со смещением обрыва.
    #     Перекачка с нуля дала бы [0]; лишние запросы изменили бы длину списка.
    assert _RangeHandler.served_ranges == [prefix]
