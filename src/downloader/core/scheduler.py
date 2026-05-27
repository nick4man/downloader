"""Непрерывный планировщик демона: пул воркеров + фидер из SQLite-очереди.

В отличие от одноразового `Engine.run_pending`, крутится постоянно: фидер
опрашивает БД на новые `queued`-задачи (добавленные по HTTP на ходу), а пул из
N воркеров их выполняет. Живой прогресс держим в памяти (`progress`) — отдаём
клиентам без задержки на запись в БД.
"""

from __future__ import annotations

import asyncio

import aiosqlite

from downloader.config import Config
from downloader.core.worker import run_job
from downloader.models import JobState, ProgressEvent
from downloader.store import jobs_repo

_FEED_INTERVAL = 1.5  # как часто фидер ищет новые queued-задачи, сек


class Scheduler:
    """Качает очередь постоянно: фидер → asyncio.Queue → N воркеров."""

    def __init__(self, conn: aiosqlite.Connection, config: Config) -> None:
        self.conn = conn
        self.config = config
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._inflight: set[str] = set()  # id, уже отданные в очередь/в работе
        self.progress: dict[str, ProgressEvent] = {}  # последний снимок на job_id
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def run_forever(self) -> None:
        """Запустить фидер и пул воркеров, крутиться до stop()."""
        # Прерванные ранее running считаем возобновляемыми.
        for job in await jobs_repo.list_jobs(self.conn, [JobState.RUNNING]):
            await jobs_repo.set_state(self.conn, job.id, JobState.QUEUED)

        self._tasks = [asyncio.create_task(self._feeder())]
        self._tasks += [
            asyncio.create_task(self._worker()) for _ in range(self.config.max_concurrent)
        ]
        await self._stop.wait()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def stop(self) -> None:
        self._stop.set()

    async def _feeder(self) -> None:
        """Периодически класть новые queued-задачи в рабочую очередь."""
        while not self._stop.is_set():
            for job in await jobs_repo.list_jobs(self.conn, [JobState.QUEUED]):
                if job.id not in self._inflight:
                    self._inflight.add(job.id)
                    self._queue.put_nowait(job.id)
            await asyncio.sleep(_FEED_INTERVAL)

    async def _worker(self) -> None:
        """Брать job_id из очереди и качать (если он всё ещё queued)."""
        while True:
            job_id = await self._queue.get()
            try:
                job = await jobs_repo.get_job(self.conn, job_id)
                if job is not None and job.state is JobState.QUEUED:
                    await run_job(
                        self.conn,
                        job,
                        self._on_progress,
                        connections=self.config.connections,
                    )
            except Exception:  # noqa: BLE001 — воркер не должен падать целиком из-за одной задачи
                pass
            finally:
                self._inflight.discard(job_id)
                self.progress.pop(job_id, None)
                self._queue.task_done()

    def _on_progress(self, ev: ProgressEvent) -> None:
        self.progress[ev.job_id] = ev
