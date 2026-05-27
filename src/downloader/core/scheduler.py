"""Непрерывный планировщик демона: пул воркеров + фидер из SQLite-очереди.

В отличие от одноразового `Engine.run_pending`, крутится постоянно: фидер
опрашивает БД на новые `queued`-задачи (добавленные по HTTP на ходу), а пул из
N воркеров их выполняет. Живой прогресс держим в памяти (`progress`) — отдаём
клиентам без задержки на запись в БД.
"""

from __future__ import annotations

import asyncio

import aiosqlite

from downloader.config import Config, effective_cookies
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
        self._active: dict[str, asyncio.Task] = {}  # job_id → задача run_job (для отмены)
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

    def cancel(self, job_id: str) -> bool:
        """Прервать уже запущенную задачу (убивает дочерний процесс). True, если была активна."""
        task = self._active.get(job_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

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
                    # Запускаем закачку отдельной задачей, чтобы её можно было
                    # отменить (cancel) — это убьёт дочерний процесс через finally.
                    task = asyncio.create_task(
                        run_job(
                            self.conn,
                            job,
                            self._on_progress,
                            connections=self.config.connections,
                            cookies=effective_cookies(self.config),
                        )
                    )
                    self._active[job_id] = task
                    try:
                        await task
                    except asyncio.CancelledError:
                        if self._stop.is_set():
                            raise  # общий shutdown воркера — выходим
                        # отменили КОНКРЕТНУЮ задачу (pause/delete) — не падаем,
                        # состояние выставит вызвавший cancel.
            except asyncio.CancelledError:
                raise  # shutdown
            except Exception:  # noqa: BLE001 — одна задача не должна ронять воркер
                pass
            finally:
                self._active.pop(job_id, None)
                self._inflight.discard(job_id)
                self.progress.pop(job_id, None)
                self._queue.task_done()

    def _on_progress(self, ev: ProgressEvent) -> None:
        self.progress[ev.job_id] = ev
