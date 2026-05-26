"""Жизненный цикл одной задачи: выбор загрузчика, прогресс, фиксация состояния."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import aiosqlite

from downloader.core.events import ProgressCallback, noop_progress
from downloader.models import DownloadJob, DownloadKind, Engine, JobState, ProgressEvent
from downloader.services import dedup, sites
from downloader.services.naming import filename_from_url, sanitize_filename
from downloader.services.resolver import choose_engine, classify
from downloader.store import jobs_repo
from downloader.tools import aria2, ffmpeg, http_downloader, ytdlp

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
    # Для медиа имя файла определит yt-dlp по шаблону; для прямых — берём из URL.
    if not job.filename and job.kind is not DownloadKind.MEDIA:
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

    result: Path | None = None
    try:
        if job.engine is Engine.YTDLP:
            # Сайт-плагин: для поддерживаемых сайтов достаём реальный источник
            # (HLS-мастер → топ-качество) и заголовок; иначе качаем как есть.
            resolved = await sites.resolve_source(job.url)
            if resolved:
                src, title = resolved
                name = sanitize_filename(title) if title else None
            else:
                src, name = job.url, None
            result = await ytdlp.download(
                src,
                job.dest_dir,
                job.fmt or "best",
                on_progress,
                job_id=job.id,
                name=name,
            )
        elif job.engine is Engine.FFMPEG:
            result = await ffmpeg.hls_to_mp4(
                job.url,
                job.dest_dir,
                job.filename or "video",
                on_progress,
                job_id=job.id,
            )
        elif job.engine is Engine.ARIA2:
            result = await aria2.download(
                job.url,
                job.dest_dir,
                job.filename or "download",
                on_progress,
                connections=connections,
                job_id=job.id,
            )
        else:  # Engine.HTTP — фолбэк
            result = await http_downloader.download(
                job.url,
                job.dest_dir,
                job.filename or "download",
                on_progress,
                job_id=job.id,
            )
    except Exception as exc:  # noqa: BLE001 — кладём текст ошибки в задачу
        job.state = JobState.ERROR
        job.error = str(exc)
        await jobs_repo.update_job(conn, job)
        return

    # yt-dlp сам именует файл — подхватываем реальное имя из вернувшегося пути.
    if result is not None:
        job.filename = result.name

    # Итоговый размер берём из ФС — это надёжнее, чем распарсенный прогресс
    # (парсер может промахнуться, особенно на быстрых закачках).
    job.state = JobState.COMPLETED
    final = Path(job.dest_dir) / job.filename if job.filename else None
    if final and final.exists():
        job.bytes_total = job.bytes_done = final.stat().st_size
        # Контент-хэш для дедупа (дубликаты распознаются по общему sha256).
        job.sha256, _ = await dedup.register(conn, final)
    elif job.bytes_total:
        job.bytes_done = job.bytes_total
    await jobs_repo.update_job(conn, job)
