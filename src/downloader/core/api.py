"""HTTP API демона (FastAPI): управление очередью + живой статус.

Lifespan поднимает Scheduler (непрерывную закачку) над общей SQLite-БД.
Эндпоинты — тонкая обёртка над jobs_repo + services.intake; CLI ходит сюда.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from downloader import __version__
from downloader.config import load_config
from downloader.core.scheduler import Scheduler
from downloader.models import DownloadJob, JobState
from downloader.services.intake import build_job
from downloader.services.naming import sanitize_filename
from downloader.store import jobs_repo
from downloader.store.db import connect


class AddRequest(BaseModel):
    url: str
    dir: str | None = None
    quality: int | None = None


class ImportRequest(BaseModel):
    urls: list[str]
    dir: str | None = None
    quality: int | None = None


class RenameRequest(BaseModel):
    filename: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    conn = await connect()
    sched = Scheduler(conn, config)
    app.state.conn = conn
    app.state.config = config
    app.state.scheduler = sched
    import asyncio

    runner = asyncio.create_task(sched.run_forever())
    try:
        yield
    finally:
        sched.stop()
        await runner
        await conn.close()


app = FastAPI(title="downloader daemon", version=__version__, lifespan=lifespan)


def _merge_live(job: DownloadJob, sched: Scheduler) -> DownloadJob:
    """Наложить живой снимок прогресса (из памяти планировщика) на задачу из БД."""
    ev = sched.progress.get(job.id)
    if ev is not None:
        job.bytes_done = ev.bytes_done
        if ev.bytes_total is not None:
            job.bytes_total = ev.bytes_total
    return job


async def _resolve(conn, sched: Scheduler, job_id: str) -> DownloadJob:
    """Найти задачу по полному id или однозначному префиксу."""
    job = await jobs_repo.get_job(conn, job_id)
    if job is None:
        matches = [j for j in await jobs_repo.list_jobs(conn) if j.id.startswith(job_id)]
        if len(matches) == 1:
            job = matches[0]
        elif not matches:
            raise HTTPException(404, f"Задача '{job_id}' не найдена")
        else:
            raise HTTPException(409, f"Префикс '{job_id}' неоднозначен")
    return _merge_live(job, sched)


_INDEX_HTML = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Веб-интерфейс (опрашивает /jobs)."""
    return _INDEX_HTML


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/jobs")
async def list_jobs() -> list[DownloadJob]:
    conn, sched = app.state.conn, app.state.scheduler
    return [_merge_live(j, sched) for j in await jobs_repo.list_jobs(conn)]


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> DownloadJob:
    return await _resolve(app.state.conn, app.state.scheduler, job_id)


@app.post("/jobs")
async def add_job(req: AddRequest) -> DownloadJob:
    job = build_job(req.url, app.state.config, dest_dir=req.dir, quality=req.quality)
    await jobs_repo.add_job(app.state.conn, job)
    return job


@app.post("/jobs/import")
async def import_jobs(req: ImportRequest) -> dict:
    conn = app.state.conn
    existing = {j.url for j in await jobs_repo.list_jobs(conn)}
    added = 0
    for url in req.urls:
        if url in existing:
            continue
        job = build_job(url, app.state.config, dest_dir=req.dir, quality=req.quality)
        await jobs_repo.add_job(conn, job)
        existing.add(url)  # чтобы дубль внутри самого списка не добавился дважды
        added += 1
    return {"added": added, "total": len(req.urls)}


@app.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str) -> DownloadJob:
    # Паузу разрешаем и для running — активный процесс прервётся (cancel).
    allowed = {JobState.QUEUED, JobState.RUNNING, JobState.ERROR}
    return await _transition(job_id, JobState.PAUSED, allowed)


@app.post("/jobs/{job_id}/rename")
async def rename_job(job_id: str, req: RenameRequest) -> DownloadJob:
    conn, sched = app.state.conn, app.state.scheduler
    job = await _resolve(conn, sched, job_id)
    job.filename = sanitize_filename(req.filename)
    await jobs_repo.update_job(conn, job)
    return job


@app.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str) -> DownloadJob:
    allowed = {JobState.PAUSED, JobState.ERROR, JobState.CANCELED}
    return await _transition(job_id, JobState.QUEUED, allowed)


async def _transition(job_id: str, target: JobState, allowed_from: set[JobState]) -> DownloadJob:
    conn, sched = app.state.conn, app.state.scheduler
    job = await _resolve(conn, sched, job_id)
    if job.state not in allowed_from:
        raise HTTPException(409, f"Нельзя перевести из '{job.state.value}' в '{target.value}'")
    if job.state is JobState.RUNNING:
        sched.cancel(job.id)  # прервать активный процесс перед сменой состояния
    await jobs_repo.set_state(conn, job.id, target)
    job.state = target
    return job


@app.delete("/jobs/{job_id}")
async def remove_job(job_id: str) -> dict:
    conn, sched = app.state.conn, app.state.scheduler
    job = await _resolve(conn, sched, job_id)
    sched.cancel(job.id)  # если качается — остановить процесс перед удалением
    await jobs_repo.delete_job(conn, job.id)
    if job.filename:
        target = Path(job.dest_dir) / job.filename
        for suffix in (".part", ".aria2"):
            target.with_suffix(target.suffix + suffix).unlink(missing_ok=True)
    return {"removed": job.id}


@app.get("/dedup")
async def dedup() -> list[dict]:
    conn = app.state.conn
    groups: dict[str, list[DownloadJob]] = defaultdict(list)
    for job in await jobs_repo.list_jobs(conn):
        if job.sha256:
            groups[job.sha256].append(job)
    return [
        {"sha256": sha, "jobs": [{"id": j.id, "filename": j.filename, "url": j.url} for j in js]}
        for sha, js in groups.items()
        if len(js) > 1
    ]


@app.post("/shutdown")
async def shutdown() -> dict:
    app.state.scheduler.stop()
    return {"ok": True}
