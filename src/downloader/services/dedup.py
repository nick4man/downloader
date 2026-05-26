"""Контент-дедуп по SHA256: хэшируем скачанные файлы и распознаём дубликаты.

Поведение неразрушающее: при совпадении хэша файлы НЕ удаляем — лишь
сообщаем об оригинале (см. `dl dedup`). Частичные файлы (.part/.aria2) не
хэшируем — у aria2 для них свои control-файлы.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import aiosqlite

from downloader.store import hashes_repo

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
