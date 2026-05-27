"""Тесты контент-дедупа (SHA256 + реестр file_hashes)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from downloader.models import DownloadJob, JobState
from downloader.services import dedup
from downloader.store import jobs_repo
from downloader.store.db import connect


@pytest.fixture
async def conn():
    c = await connect(":memory:")
    try:
        yield c
    finally:
        await c.close()


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    f = tmp_path / "x.bin"
    data = b"payload" * 5000
    f.write_bytes(data)
    assert dedup.sha256_file(f) == hashlib.sha256(data).hexdigest()


async def test_register_detects_duplicate(conn, tmp_path: Path) -> None:
    same = b"hello world" * 1000
    a = tmp_path / "a.bin"
    a.write_bytes(same)
    b = tmp_path / "b.bin"
    b.write_bytes(same)  # тот же контент, другой путь
    c = tmp_path / "c.bin"
    c.write_bytes(b"different content")

    sha_a, dup_a = await dedup.register(conn, a)
    assert dup_a is None  # первый файл — оригинал

    sha_b, dup_b = await dedup.register(conn, b)
    assert sha_b == sha_a
    assert dup_b == str(a)  # b распознан как дубликат a

    _, dup_c = await dedup.register(conn, c)
    assert dup_c is None  # другой контент — не дубликат

    # Повторная регистрация того же пути дубликатом не считается.
    _, dup_a_again = await dedup.register(conn, a)
    assert dup_a_again is None


async def test_reconcile_keeps_best_quality(conn, tmp_path) -> None:
    lo = tmp_path / "lo.mp4"
    lo.write_bytes(b"x" * 100)
    hi = tmp_path / "hi.mp4"
    hi.write_bytes(b"x" * 200)
    j_lo = DownloadJob(
        url="https://e.com/1", dest_dir=str(tmp_path), filename="lo.mp4",
        state=JobState.COMPLETED, source_id="yt:abc", height=480, bytes_done=100,
    )
    j_hi = DownloadJob(
        url="https://e.com/2", dest_dir=str(tmp_path), filename="hi.mp4",
        state=JobState.COMPLETED, source_id="yt:abc", height=1080, bytes_done=200,
    )
    await jobs_repo.add_job(conn, j_lo)
    await jobs_repo.add_job(conn, j_hi)

    removed = await dedup.reconcile_quality(conn, j_hi)  # hi только что завершён
    assert removed == 1
    remaining = await jobs_repo.list_jobs(conn)
    assert [j.id for j in remaining] == [j_hi.id]  # остался лучший
    assert not lo.exists() and hi.exists()  # худший файл удалён


async def test_reconcile_audio_video_separate(conn, tmp_path) -> None:
    # аудио и видео одного source_id — не вытесняют друг друга
    v = DownloadJob(url="https://e.com/v", dest_dir=str(tmp_path), filename="v.mp4",
                    state=JobState.COMPLETED, source_id="yt:x", height=720, audio=False)
    a = DownloadJob(url="https://e.com/a", dest_dir=str(tmp_path), filename="a.mp3",
                    state=JobState.COMPLETED, source_id="yt:x", audio=True)
    await jobs_repo.add_job(conn, v)
    await jobs_repo.add_job(conn, a)
    assert await dedup.reconcile_quality(conn, v) == 0  # аудио не трогаем
    assert len(await jobs_repo.list_jobs(conn)) == 2
