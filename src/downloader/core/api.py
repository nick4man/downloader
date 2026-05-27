"""HTTP API демона (FastAPI): управление очередью + живой статус.

Lifespan поднимает Scheduler (непрерывную закачку) над общей SQLite-БД.
Эндпоинты — тонкая обёртка над jobs_repo + services.intake; CLI ходит сюда.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from downloader import __version__
from downloader.config import COOKIES_PATH, load_config
from downloader.core.scheduler import Scheduler
from downloader.models import DownloadJob, JobState
from downloader.services.intake import build_job
from downloader.services.naming import sanitize_filename
from downloader.services.scrape import extract_urls
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


class MoveRequest(BaseModel):
    direction: str  # "up" | "down"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    conn = await connect()
    sched = Scheduler(conn, config)
    app.state.conn = conn
    app.state.config = config
    app.state.scheduler = sched
    runner = asyncio.create_task(sched.run_forever())
    try:
        yield
    finally:
        sched.stop()
        await runner
        await conn.close()


app = FastAPI(title="downloader daemon", version=__version__, lifespan=lifespan)

# CORS — чтобы букмарклет/расширение могли слать URL с чужих сайтов (youtube и т.п.).
app.add_middleware(
    CORSMiddleware,
    allow_origins=load_config().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Публичная оболочка (грузится без токена); API за ней — под токеном.
_PUBLIC_PATHS = {"/health", "/", "/manifest.webmanifest", "/sw.js", "/icon.svg"}


def _supplied_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("dl_token") or request.query_params.get("token")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    token = getattr(app.state, "config", None)
    token = token.auth_token if token else None
    # OPTIONS (CORS-preflight) и публичные пути — без токена.
    if (
        token
        and request.method != "OPTIONS"
        and request.url.path not in _PUBLIC_PATHS
        and _supplied_token(request) != token
    ):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    response = await call_next(request)
    # ?token=… в URL → ставим cookie, дальше морда/share работают прозрачно.
    if token and request.query_params.get("token") == token:
        response.set_cookie("dl_token", token, max_age=31_536_000, samesite="lax")
    return response


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


_WEB = Path(__file__).parent / "web"
_INDEX_HTML = (_WEB / "index.html").read_text(encoding="utf-8")
_MANIFEST = (_WEB / "manifest.webmanifest").read_text(encoding="utf-8")
_SW = (_WEB / "sw.js").read_text(encoding="utf-8")
_ICON = (_WEB / "icon.svg").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Веб-интерфейс (опрашивает /jobs)."""
    return _INDEX_HTML


@app.get("/manifest.webmanifest")
async def manifest() -> Response:
    return Response(_MANIFEST, media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker() -> Response:
    return Response(_SW, media_type="application/javascript")


@app.get("/icon.svg")
async def icon() -> Response:
    return Response(_ICON, media_type="image/svg+xml")


@app.get("/share")
async def share(url: str = "", text: str = "", title: str = "") -> RedirectResponse:
    """Web Share Target (Android PWA): принять расшаренный URL и поставить в очередь.

    Android кладёт ссылку то в `url`, то в `text` — достаём из всех полей.
    """
    candidates = [url, *extract_urls(text), *extract_urls(title)]
    target = next((u for u in candidates if u.startswith("http")), None)
    if target:
        job = build_job(target, app.state.config)
        await jobs_repo.add_job(app.state.conn, job)
    return RedirectResponse("/", status_code=303)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "version": __version__}


@app.websocket("/ws")
async def ws_jobs(websocket: WebSocket) -> None:
    """Стрим состояния задач: push полного списка (с живым прогрессом) раз в 0.5с."""
    token = app.state.config.auth_token
    if token:
        supplied = websocket.cookies.get("dl_token") or websocket.query_params.get("token")
        if supplied != token:
            await websocket.close(code=1008)  # policy violation
            return
    await websocket.accept()
    conn, sched = app.state.conn, app.state.scheduler
    try:
        while True:
            jobs = await jobs_repo.list_jobs(conn)
            payload = [_merge_live(j, sched).model_dump(mode="json") for j in jobs]
            await websocket.send_json(payload)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass


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


@app.post("/jobs/{job_id}/move")
async def move_job(job_id: str, req: MoveRequest) -> list[DownloadJob]:
    conn, sched = app.state.conn, app.state.scheduler
    job = await _resolve(conn, sched, job_id)
    jobs = await jobs_repo.list_jobs(conn)
    ids = [j.id for j in jobs]
    idx = ids.index(job.id)
    k = idx - 1 if req.direction == "up" else idx + 1
    if 0 <= k < len(ids):
        ids[idx], ids[k] = ids[k], ids[idx]
        await jobs_repo.reorder(conn, ids)
    return [_merge_live(j, sched) for j in await jobs_repo.list_jobs(conn)]


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


@app.get("/cookies")
async def cookies_status() -> dict:
    """Загружен ли cookies.txt (для age-gate/приватного контента)."""
    size = COOKIES_PATH.stat().st_size if COOKIES_PATH.exists() else 0
    return {"present": COOKIES_PATH.exists(), "bytes": size}


@app.post("/cookies")
async def upload_cookies(request: Request) -> dict:
    """Сохранить присланный cookies.txt (Netscape-формат) — тело запроса = файл."""
    raw = await request.body()
    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    COOKIES_PATH.write_bytes(raw)
    return {"ok": True, "bytes": len(raw)}


@app.delete("/cookies")
async def delete_cookies() -> dict:
    COOKIES_PATH.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/reload")
async def reload_config() -> dict:
    """Перечитать config.toml на лету (download_dir/качество/connections для
    новых задач). Размер пула воркеров меняется только через restart."""
    cfg = load_config()
    app.state.config = cfg
    app.state.scheduler.config = cfg
    return {"ok": True, "max_concurrent": cfg.max_concurrent}


@app.post("/shutdown")
async def shutdown() -> dict:
    app.state.scheduler.stop()
    return {"ok": True}
