"""Обёртка над aria2c: сегментная докачка + разбор прогресса.

Соблюдаем паттерн скилла: subprocess списком аргументов, парсинг stdout,
коды возврата не глотаем. Resume обеспечивает сам aria2 через `-c` и `.aria2`.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from downloader.core.events import ProgressCallback, noop_progress
from downloader.models import ProgressEvent
from downloader.tools.base import resolve_binary

# Пример строки прогресса:
# [#0a3f8e 4.5MiB/19MiB(23%) CN:5 DL:2.3MiB ETA:6s]
_PROGRESS = re.compile(
    r"(?P<done>[\d.]+)(?P<du>[KMGT]i?B|B)/(?P<total>[\d.]+)(?P<tu>[KMGT]i?B|B)"
    r"\((?P<pct>\d+)%\)"
    r"(?:.*?DL:(?P<spd>[\d.]+)(?P<su>[KMGT]i?B|B))?"
    r"(?:.*?ETA:(?P<eta>[\dhms]+))?"
)
_UNITS = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30, "TiB": 1 << 40}
_UNITS.update({"KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4})


def _to_bytes(num: str, unit: str) -> int:
    return int(float(num) * _UNITS.get(unit, 1))


def _parse_eta(raw: str | None) -> float | None:
    """Разобрать ETA вида '6s', '1m30s', '1h2m' в секунды."""
    if not raw:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", raw)
    if not m or not any(m.groups()):
        return None
    h, mn, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mn * 60 + s


async def _iter_lines(stream: asyncio.StreamReader):
    r"""Отдавать «логические» строки aria2, разделённые \r или \n.

    aria2 перерисовывает строку прогресса возвратом каретки (\r) без перевода
    строки, поэтому построчное чтение по \n не отдавало бы обновления до конца
    процесса. Читаем чанками и режем по обоим разделителям.
    """
    buf = ""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        buf += chunk.decode(errors="replace")
        parts = re.split(r"[\r\n]+", buf)
        buf = parts.pop()  # последний фрагмент может быть неполным — копим дальше
        for part in parts:
            if part.strip():
                yield part.strip()
    if buf.strip():
        yield buf.strip()


def parse_progress(line: str, job_id: str = "") -> ProgressEvent | None:
    """Разобрать строку прогресса aria2c в ProgressEvent (или None)."""
    m = _PROGRESS.search(line)
    if not m:
        return None
    return ProgressEvent(
        job_id=job_id,
        bytes_done=_to_bytes(m["done"], m["du"]),
        bytes_total=_to_bytes(m["total"], m["tu"]),
        percent=float(m["pct"]),
        speed=_to_bytes(m["spd"], m["su"]) if m["spd"] else None,
        eta=_parse_eta(m["eta"]),
    )


async def download(
    url: str,
    dest_dir: Path | str,
    filename: str,
    on_progress: ProgressCallback = noop_progress,
    *,
    connections: int = 16,
    job_id: str = "",
) -> Path:
    """Скачать url через aria2c с докачкой. Вернуть путь; ошибку поднять при ненулевом коде."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    aria2c = resolve_binary("aria2c")
    args = [
        aria2c,
        "-c",
        f"-x{connections}",
        f"-s{connections}",
        "--summary-interval=1",
        "--console-log-level=warn",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        # Устойчивость к зависающим соединениям (full-tunnel VPN и пр.):
        "--max-tries=5",
        "--retry-wait=2",
        "--connect-timeout=15",
        "--timeout=30",
        "--lowest-speed-limit=1K",  # зависшее соединение сбросить и пересоздать
        "-d",
        str(dest_dir),
        "-o",
        filename,
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    tail: list[str] = []
    async for line in _iter_lines(proc.stdout):
        tail.append(line)
        del tail[:-20]  # держим только хвост для диагностики ошибок
        event = parse_progress(line, job_id)
        if event:
            on_progress(event)

    code = await proc.wait()
    if code != 0:
        raise RuntimeError(f"aria2c вышел с кодом {code}:\n" + "\n".join(tail[-5:]))
    return dest_dir / filename
