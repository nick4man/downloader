"""SQLite-хранилище: подключение, схема и миграции (aiosqlite)."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from downloader.config import DB_PATH

SCHEMA_VERSION = 4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    kind        TEXT NOT NULL,
    dest_dir    TEXT NOT NULL,
    filename    TEXT,
    fmt         TEXT,
    engine      TEXT,
    state       TEXT NOT NULL,
    bytes_done  INTEGER NOT NULL DEFAULT 0,
    bytes_total INTEGER,
    sha256      TEXT,
    error       TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    audio       INTEGER NOT NULL DEFAULT 0,
    source_id   TEXT,
    height      INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);

CREATE TABLE IF NOT EXISTS history (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id  TEXT NOT NULL,
    event   TEXT NOT NULL,
    ts      TEXT NOT NULL,
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_job ON history(job_id);

CREATE TABLE IF NOT EXISTS file_hashes (
    sha256     TEXT PRIMARY KEY,
    path       TEXT NOT NULL,
    size       INTEGER NOT NULL,
    first_seen TEXT NOT NULL
);
"""


async def connect(path: Path | str = DB_PATH) -> aiosqlite.Connection:
    """Открыть соединение, создав каталог и применив схему."""
    path = Path(path)
    if path != Path(":memory:"):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    if path != Path(":memory:"):
        # WAL: одновременные читатели + один писатель без взаимных блокировок;
        # busy_timeout: писатель ждёт освобождения, а не падает с «database is locked».
        # Важно для связки демон + CLI, пишущих в одну БД.
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA busy_timeout = 5000")
    await _migrate(conn)
    return conn


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Применить схему и проставить версию (простая миграция вперёд)."""
    await conn.executescript(_SCHEMA)  # создаёт таблицы для новой БД
    # v1 → v2: добавить колонку position в существующую таблицу jobs.
    async with conn.execute("PRAGMA table_info(jobs)") as cur:
        columns = {row[1] for row in await cur.fetchall()}
    if "position" not in columns:
        await conn.execute("ALTER TABLE jobs ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
    if "audio" not in columns:  # v2 → v3
        await conn.execute("ALTER TABLE jobs ADD COLUMN audio INTEGER NOT NULL DEFAULT 0")
    if "source_id" not in columns:  # v3 → v4: дедуп по идентичности источника
        await conn.execute("ALTER TABLE jobs ADD COLUMN source_id TEXT")
        await conn.execute("ALTER TABLE jobs ADD COLUMN height INTEGER")
    await conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    await conn.commit()
