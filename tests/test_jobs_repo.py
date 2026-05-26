"""Тесты персистентности задач (in-memory SQLite)."""

from __future__ import annotations

import pytest

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


async def test_add_get_roundtrip(conn) -> None:
    job = DownloadJob(url="https://e.com/f.bin", dest_dir="/tmp")
    await jobs_repo.add_job(conn, job)
    loaded = await jobs_repo.get_job(conn, job.id)
    assert loaded is not None
    assert loaded.url == job.url
    assert loaded.state is JobState.QUEUED


async def test_update_and_set_state(conn) -> None:
    job = DownloadJob(url="https://e.com/f.bin", dest_dir="/tmp")
    await jobs_repo.add_job(conn, job)

    job.bytes_total = 1000
    job.bytes_done = 500
    await jobs_repo.update_job(conn, job)
    await jobs_repo.set_state(conn, job.id, JobState.COMPLETED)

    loaded = await jobs_repo.get_job(conn, job.id)
    assert loaded is not None
    assert loaded.bytes_done == 500
    assert loaded.state is JobState.COMPLETED


async def test_list_filter_and_delete(conn) -> None:
    j1 = DownloadJob(url="https://e.com/1", dest_dir="/tmp", state=JobState.QUEUED)
    j2 = DownloadJob(url="https://e.com/2", dest_dir="/tmp", state=JobState.COMPLETED)
    await jobs_repo.add_job(conn, j1)
    await jobs_repo.add_job(conn, j2)

    queued = await jobs_repo.list_jobs(conn, [JobState.QUEUED])
    assert [j.id for j in queued] == [j1.id]
    assert len(await jobs_repo.list_jobs(conn)) == 2

    await jobs_repo.delete_job(conn, j1.id)
    assert len(await jobs_repo.list_jobs(conn)) == 1
