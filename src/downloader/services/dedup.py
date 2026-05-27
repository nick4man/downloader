"""Контент-дедуп по SHA256: хэшируем скачанные файлы и распознаём дубликаты.

Поведение неразрушающее: при совпадении хэша файлы НЕ удаляем — лишь
сообщаем об оригинале (см. `dl dedup`). Частичные файлы (.part/.aria2) не
хэшируем — у aria2 для них свои control-файлы.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from pathlib import Path

import aiosqlite

from downloader.models import DownloadJob, JobState
from downloader.store import hashes_repo, jobs_repo

_CHUNK = 1 << 20  # 1 MiB


def sha256_file(path: Path | str) -> str:
    """Посчитать SHA256 файла, читая его кусками (не держим в памяти целиком)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


async def register(conn: aiosqlite.Connection, path: Path | str) -> tuple[str, str | None]:
    """Захэшировать файл и записать в реестр.

    Возвращает (sha256, путь_оригинала). `путь_оригинала` непустой, если этот
    контент уже встречался под другим (существующим) путём — то есть это дубликат.
    """
    path = Path(path)
    sha = await asyncio.to_thread(sha256_file, path)
    existing = await hashes_repo.find_hash(conn, sha)
    if existing and existing != str(path) and Path(existing).exists():
        return sha, existing  # дубликат уже скачанного файла — реестр не трогаем
    await hashes_repo.record_hash(conn, sha, str(path), path.stat().st_size)
    return sha, None


def _quality(job: DownloadJob) -> tuple[int, int]:
    """Метрика качества: выше разрешение, затем больше размер."""
    return (job.height or 0, job.bytes_done or 0)


async def reconcile_quality(conn: aiosqlite.Connection, job: DownloadJob) -> int:
    """Среди завершённых задач того же source_id и режима оставить лучшее качество.

    Файлы и записи худших удаляются (режим «заменять лучшим»). Возвращает число
    удалённых дубликатов. Прямые файлы (source_id=None) не участвуют.
    """
    group = [
        j
        for j in await jobs_repo.list_jobs(conn, [JobState.COMPLETED])
        if j.source_id and j.source_id == job.source_id and j.audio == job.audio
    ]
    if len(group) < 2:
        return 0
    best = max(group, key=_quality)
    removed = 0
    for other in group:
        if other.id == best.id:
            continue
        if other.filename:  # снести файл худшего качества
            with contextlib.suppress(OSError):
                (Path(other.dest_dir) / other.filename).unlink(missing_ok=True)
        await jobs_repo.delete_job(conn, other.id)
        removed += 1
    return removed
