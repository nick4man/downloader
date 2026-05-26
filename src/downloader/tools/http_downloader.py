"""Чистый Python HTTP-загрузчик с докачкой (фолбэк, когда нет aria2).

Качает в файл `<filename>.part`, поддерживает возобновление через Range-запрос,
по завершении переименовывает в финальное имя. Устойчив к зависающим соединениям:
раздельные connect/read таймауты + ретраи, докачивающие `.part` с места обрыва.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from downloader.core.events import ProgressCallback, noop_progress
from downloader.models import ProgressEvent

_CHUNK = 1 << 16  # 64 KiB
_MAX_TRIES = 5
_RETRY_WAIT = 2.0  # сек между попытками
# connect=15с, read=30с: зависший туннель → ReadTimeout, а не вечная блокировка.
_TIMEOUT = httpx.Timeout(15.0, read=30.0)
# Браузерный UA: многие CDN отдают 403 клиентам без «настоящего» User-Agent.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


async def download(
    url: str,
    dest_dir: Path | str,
    filename: str,
    on_progress: ProgressCallback = noop_progress,
    *,
    job_id: str = "",
) -> Path:
    """Скачать url в dest_dir/filename с докачкой и ретраями. Вернуть путь к файлу."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    part = target.with_suffix(target.suffix + ".part")

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_TRIES + 1):
        try:
            await _stream_to_part(url, part, on_progress, job_id)
            part.replace(target)
            return target
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            # Сетевой сбой/зависание: ждём и пробуем снова — .part уже на диске,
            # следующая попытка докачает его Range-запросом с места обрыва.
            last_exc = exc
            if attempt < _MAX_TRIES:
                await asyncio.sleep(_RETRY_WAIT)
    raise RuntimeError(f"http: не удалось скачать за {_MAX_TRIES} попыток: {last_exc}")


async def _stream_to_part(
    url: str, part: Path, on_progress: ProgressCallback, job_id: str
) -> None:
    """Одна попытка: стримить тело в `.part`, докачивая с уже скачанного префикса."""
    resume_from = part.stat().st_size if part.exists() else 0
    headers = dict(_HEADERS)
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"

    async with (
        httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT) as client,
        client.stream("GET", url, headers=headers) as resp,
    ):
        # Сервер не поддержал докачку — начинаем заново.
        if resume_from and resp.status_code == 200:
            resume_from = 0
            part.unlink(missing_ok=True)
        resp.raise_for_status()

        total = _total_size(resp, resume_from)
        mode = "ab" if resume_from else "wb"
        done = resume_from
        with part.open(mode) as fh:
            async for chunk in resp.aiter_bytes(_CHUNK):
                fh.write(chunk)
                done += len(chunk)
                on_progress(
                    ProgressEvent(
                        job_id=job_id,
                        bytes_done=done,
                        bytes_total=total,
                        percent=(100 * done / total) if total else None,
                    )
                )


def _total_size(resp: httpx.Response, resume_from: int) -> int | None:
    """Полный размер файла с учётом уже скачанного префикса."""
    length = resp.headers.get("Content-Length")
    if length is None:
        return None
    return int(length) + resume_from
