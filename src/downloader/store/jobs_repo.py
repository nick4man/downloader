"""CRUD-операции над задачами в SQLite."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import aiosqlite

from downloader.models import DownloadJob, JobState

_COLUMNS = (
    "id, url, kind, dest_dir, filename, fmt, engine, state, "
    "bytes_done, bytes_total, sha256, error, position, audio, created_at, updated_at"
)


def _row_to_job(row: aiosqlite.Row) -> DownloadJob:
    """Собрать модель из строки БД (pydantic валидирует enum'ы и даты)."""
    return DownloadJob.model_validate(dict(row))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def add_job(conn: aiosqlite.Connection, job: DownloadJob) -> None:
    """Вставить новую задачу (в конец очереди — position = max+1)."""
    async with conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM jobs") as cur:
        (job.position,) = await cur.fetchone()
    await conn.execute(
        f"INSERT INTO jobs ({_COLUMNS}) VALUES "
        "(:id, :url, :kind, :dest_dir, :filename, :fmt, :engine, :state, "
        ":bytes_done, :bytes_total, :sha256, :error, :position, :audio, "
        ":created_at, :updated_at)",
        _job_params(job),
    )
    await conn.commit()


async def update_job(conn: aiosqlite.Connection, job: DownloadJob) -> None:
    """Сохранить изменяемые поля задачи и обновить updated_at."""
    job.updated_at = datetime.now(UTC)
    await conn.execute(
        "UPDATE jobs SET kind=:kind, filename=:filename, fmt=:fmt, engine=:engine, "
        "state=:state, bytes_done=:bytes_done, bytes_total=:bytes_total, "
        "sha256=:sha256, error=:error, position=:position, updated_at=:updated_at WHERE id=:id",
        _job_params(job),
    )
    await conn.commit()


async def set_state(
    conn: aiosqlite.Connection,
    job_id: str,
    state: JobState,
    error: str | None = None,
) -> None:
    """Быстро обновить только состояние (и ошибку)."""
    await conn.execute(
        "UPDATE jobs SET state=?, error=?, updated_at=? WHERE id=?",
        (state.value, error, _now_iso(), job_id),
    )
    await conn.commit()


async def get_job(conn: aiosqlite.Connection, job_id: str) -> DownloadJob | None:
    """Получить задачу по id."""
    async with conn.execute(f"SELECT {_COLUMNS} FROM jobs WHERE id=?", (job_id,)) as cur:
        row = await cur.fetchone()
    return _row_to_job(row) if row else None


async def list_jobs(
    conn: aiosqlite.Connection,
    states: Iterable[JobState] | None = None,
) -> list[DownloadJob]:
    """Список задач, опционально отфильтрованный по состояниям."""
    sql = f"SELECT {_COLUMNS} FROM jobs"
    params: tuple[str, ...] = ()
    if states is not None:
        states = list(states)
        placeholders = ",".join("?" * len(states))
        sql += f" WHERE state IN ({placeholders})"
        params = tuple(s.value for s in states)
    sql += " ORDER BY position, created_at"
    async with conn.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [_row_to_job(r) for r in rows]


async def delete_job(conn: aiosqlite.Connection, job_id: str) -> None:
    """Удалить задачу."""
    await conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    await conn.commit()


async def reorder(conn: aiosqlite.Connection, ordered_ids: list[str]) -> None:
    """Записать position = индекс по заданному порядку id (один коммит)."""
    for pos, job_id in enumerate(ordered_ids):
        await conn.execute("UPDATE jobs SET position=? WHERE id=?", (pos, job_id))
    await conn.commit()


def _job_params(job: DownloadJob) -> dict:
    """Преобразовать модель в параметры для SQL (enum'ы → str, даты → ISO)."""
    return {
        "id": job.id,
        "url": job.url,
        "kind": job.kind.value,
        "dest_dir": job.dest_dir,
        "filename": job.filename,
        "fmt": job.fmt,
        "engine": job.engine.value if job.engine else None,
        "state": job.state.value,
        "bytes_done": job.bytes_done,
        "bytes_total": job.bytes_total,
        "sha256": job.sha256,
        "error": job.error,
        "position": job.position,
        "audio": int(job.audio),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }
