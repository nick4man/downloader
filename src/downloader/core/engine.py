"""Движок: раскладывает очередь по воркерам с ограничением конкурентности."""

from __future__ import annotations

import asyncio

import aiosqlite

from downloader.config import Config
from downloader.core.events import ProgressCallback, noop_progress
from downloader.core.worker import run_job
from downloader.models import JobState
from downloader.store import jobs_repo


class Engine:
    """Однопроходный обработчик очереди (Phase 1).

    Очередь и пауза/возобновление между процессами появятся в Phase 4;
    здесь мы за один запуск дренируем все незавершённые задачи.
    """

    def __init__(self, conn: aiosqlite.Connection, config: Config) -> None:
        self.conn = conn
        self.config = config
        self._sem = asyncio.Semaphore(config.max_concurrent)

    async def run_pending(self, ui_progress: ProgressCallback = noop_progress) -> int:
        """Обработать все queued-задачи. Вернуть их количество.

        Прерванные ранее running-задачи возобновляем (reset → queued).
        Явно поставленные на паузу (paused) пропускаем — их вернёт `dl resume`.
        """
        await self._reset_stale_running()
        jobs = await jobs_repo.list_jobs(self.conn, [JobState.QUEUED])
        if not jobs:
            return 0
        await asyncio.gather(*(self._run_one(j.id, ui_progress) for j in jobs))
        return len(jobs)

    async def _run_one(self, job_id: str, ui_progress: ProgressCallback) -> None:
        async with self._sem:
            job = await jobs_repo.get_job(self.conn, job_id)
            if job is None:
                return
            await run_job(self.conn, job, ui_progress, connections=self.config.connections)

    async def _reset_stale_running(self) -> None:
        """Сбросить зависшие running → queued (процесс прервали ранее)."""
        stale = await jobs_repo.list_jobs(self.conn, [JobState.RUNNING])
        for job in stale:
            await jobs_repo.set_state(self.conn, job.id, JobState.QUEUED)
