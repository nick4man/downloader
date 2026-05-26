"""Доступ к таблице file_hashes (контент-дедуп по SHA256)."""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite


async def find_hash(conn: aiosqlite.Connection, sha256: str) -> str | None:
    """Вернуть путь файла, ранее записанного под этим хэшем (или None)."""
    async with conn.execute("SELECT path FROM file_hashes WHERE sha256=?", (sha256,)) as cur:
        row = await cur.fetchone()
    return row["path"] if row else None


async def record_hash(conn: aiosqlite.Connection, sha256: str, path: str, size: int) -> None:
    """Записать (или обновить) хэш файла. При конфликте перезаписываем путь."""
    await conn.execute(
        "INSERT INTO file_hashes (sha256, path, size, first_seen) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(sha256) DO UPDATE SET path=excluded.path, size=excluded.size",
        (sha256, path, size, datetime.now(UTC).isoformat()),
    )
    await conn.commit()
