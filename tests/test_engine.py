"""Тесты диспетчеризации движка: какие состояния обрабатываются."""

from __future__ import annotations

import pytest

from downloader.config import Config
from downloader.core.engine import Engine
from downloader.models import DownloadJob, JobState
from downloader.store import jobs_repo
from downloader.store.db import connect


@pytest.fixture
async def conn():
    c = await connect(":memory:")
    try:
        yield c
    finally:
        await c.close()


async def test_run_pending_skips_paused_and_resumes_stale(conn, monkeypatch) -> None:
    ran: list[str] = []

    async def fake_run_job(c, job, ui, *, connections=16):
        ran.append(job.id)
        await jobs_repo.set_state(c, job.id, JobState.COMPLETED)

    # Подменяем реальную закачку — проверяем только выбор задач движком.
    monkeypatch.setattr("downloader.core.engine.run_job", fake_run_job)

    queued = DownloadJob(url="https://e.com/q", dest_dir="/tmp", state=JobState.QUEUED)
    paused = DownloadJob(url="https://e.com/p", dest_dir="/tmp", state=JobState.PAUSED)
    stale = DownloadJob(url="https://e.com/r", dest_dir="/tmp", state=JobState.RUNNING)
    done = DownloadJob(url="https://e.com/d", dest_dir="/tmp", state=JobState.COMPLETED)
    for job in (queued, paused, stale, done):
        await jobs_repo.add_job(conn, job)

    count = await Engine(conn, Config()).run_pending()

    # queued — обработан; stale running — возобновлён; paused и completed — нет.
    assert queued.id in ran
    assert stale.id in ran
    assert paused.id not in ran
    assert done.id not in ran
    assert count == 2
    # Пауза сохранилась нетронутой.
    reloaded = await jobs_repo.get_job(conn, paused.id)
    assert reloaded is not None and reloaded.state is JobState.PAUSED
