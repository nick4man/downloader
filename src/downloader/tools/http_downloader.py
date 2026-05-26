"""Чистый Python HTTP-загрузчик с докачкой (фолбэк, когда нет aria2).

Качает в файл `<filename>.part`, поддерживает возобновление через Range-запрос,
по завершении переименовывает в финальное имя.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from downloader.core.events import ProgressCallback, noop_progress
from downloader.models import ProgressEvent

_CHUNK = 1 << 16  # 64 KiB


async def download(
    url: str,
    dest_dir: Path | str,
    filename: str,
    on_progress: ProgressCallback = noop_progress,
    *,
    job_id: str = "",
) -> Path:
    """Скачать url в dest_dir/filename с поддержкой докачки. Вернуть путь к файлу."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    part = target.with_suffix(target.suffix + ".part")

    resume_from = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}

    async with (
        httpx.AsyncClient(follow_redirects=True, timeout=None) as client,
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

    part.replace(target)
    return target


def _total_size(resp: httpx.Response, resume_from: int) -> int | None:
    """Полный размер файла с учётом уже скачанного префикса."""
    length = resp.headers.get("Content-Length")
    if length is None:
        return None
    return int(length) + resume_from
