"""Жизненный цикл одной задачи: выбор загрузчика, прогресс, фиксация состояния."""

from __future__ import annotations

import asyncio
import time

import aiosqlite

from downloader.core.events import ProgressCallback, noop_progress
from downloader.models import DownloadJob, Engine, JobState, ProgressEvent
from downloader.services.naming import filename_from_url
from downloader.services.resolver import choose_engine, classify
from downloader.store import jobs_repo
from downloader.tools import aria2, http_downloader

_PERSIST_INTERVAL = 1.0  # как часто сбрасывать bytes_done в БД, сек


async def run_job(
    conn: aiosqlite.Connection,
    job: DownloadJob,
    ui_progress: ProgressCallback = noop_progress,
    *,
    connections: int = 16,
) -> None:
    """Выполнить задачу: подготовить, скачать, зафиксировать итог в БД."""
    # Доопределяем тип/движок/имя, если их ещё нет (первый запуск задачи).
    if job.engine is None:
        job.kind = classify(job.url)
        job.engine = choose_engine(job.kind)
    if not job.filename:
        job.filename = filename_from_url(job.url)

    job.state = JobState.RUNNING
    job.error = None
    await jobs_repo.update_job(conn, job)

    last_persist = 0.0

    def on_progress(ev: ProgressEvent) -> None:
        nonlocal last_persist
        job.bytes_done = ev.bytes_done
        if ev.bytes_total is not None:
            job.bytes_total = ev.bytes_total
        ui_progress(ev)
        now = time.monotonic()
        if now - last_persist >= _PERSIST_INTERVAL:
            last_persist = now
            # Сброс прогресса в БД — fire-and-forget, чтобы не тормозить чтение потока.
            asyncio.create_task(jobs_repo.update_job(conn, job.model_copy()))

    try:
        if job.engine is Engine.ARIA2:
            await aria2.download(
                job.url,
                job.dest_dir,
                job.filename,
                on_progress,
                connections=connections,
                job_id=job.id,
            )
        else:  # Engine.HTTP — фолбэк
            await http_downloader.download(
                job.url,
                job.dest_dir,
                job.filename,
                on_progress,
                job_id=job.id,
            )
    except Exception as exc:  # noqa: BLE001 — кладём текст ошибки в задачу
        job.state = JobState.ERROR
        job.error = str(exc)
        await jobs_repo.update_job(conn, job)
        return

    job.state = JobState.COMPLETED
    if job.bytes_total:
        job.bytes_done = job.bytes_total
    await jobs_repo.update_job(conn, job)
