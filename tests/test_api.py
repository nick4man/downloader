"""Тесты HTTP API демона (FastAPI TestClient, in-memory БД, без сети)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from downloader.models import JobState
from downloader.store import jobs_repo
from downloader.store.db import connect


@pytest.fixture
def client(monkeypatch):
    # Изолируем БД (in-memory) и глушим реальную закачку в планировщике.
    async def mem_connect(*_a, **_k):
        return await connect(":memory:")

    async def noop_run_job(conn, job, *_a, **_k):
        await jobs_repo.set_state(conn, job.id, JobState.COMPLETED)

    monkeypatch.setattr("downloader.core.api.connect", mem_connect)
    monkeypatch.setattr("downloader.core.scheduler.run_job", noop_run_job)

    from downloader.core.api import app

    with TestClient(app) as c:
        yield c


def test_health(client) -> None:
    assert client.get("/health").json()["ok"] is True


def test_reload(client) -> None:
    r = client.post("/reload").json()
    assert r["ok"] is True
    assert "max_concurrent" in r


def test_web_ui_served(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "downloader" in r.text and "/jobs" in r.text  # страница опрашивает API


def test_add_list_get(client) -> None:
    job = client.post("/jobs", json={"url": "https://youtube.com/watch?v=x"}).json()
    assert job["kind"] == "media"
    assert job["fmt"]  # для медиа проставлен -f

    jobs = client.get("/jobs").json()
    assert len(jobs) == 1
    fetched = client.get(f"/jobs/{job['id'][:8]}").json()  # резолв по префиксу
    assert fetched["id"] == job["id"]


def test_pause_invalid_transition(client) -> None:
    job = client.post("/jobs", json={"url": "https://e.com/f.zip"}).json()
    client.post(f"/jobs/{job['id']}/pause")  # queued → paused (ок)
    # paused → pause снова нельзя (allowed_from не содержит paused)
    r = client.post(f"/jobs/{job['id']}/pause")
    assert r.status_code == 409


def test_rename(client) -> None:
    job = client.post("/jobs", json={"url": "https://e.com/f.zip"}).json()
    renamed = client.post(f"/jobs/{job['id']}/rename", json={"filename": 'bad/name:?.zip'}).json()
    # имя санитизируется (запрещённые символы убраны)
    assert "/" not in renamed["filename"] and ":" not in renamed["filename"]
    assert client.get(f"/jobs/{job['id']}").json()["filename"] == renamed["filename"]


def test_move_reorder(client) -> None:
    a = client.post("/jobs", json={"url": "https://e.com/a.zip"}).json()["id"]
    b = client.post("/jobs", json={"url": "https://e.com/b.zip"}).json()["id"]
    c = client.post("/jobs", json={"url": "https://e.com/c.zip"}).json()["id"]
    assert [j["id"] for j in client.get("/jobs").json()] == [a, b, c]  # порядок добавления
    client.post(f"/jobs/{c}/move", json={"direction": "up"})  # c вверх
    assert [j["id"] for j in client.get("/jobs").json()] == [a, c, b]
    client.post(f"/jobs/{a}/move", json={"direction": "down"})  # a вниз
    assert [j["id"] for j in client.get("/jobs").json()] == [c, a, b]


def test_import_dedup_404(client) -> None:
    res = client.post("/jobs/import", json={"urls": ["https://a.com/1", "https://a.com/1"]}).json()
    assert res == {"added": 1, "total": 2}  # дубль в списке схлопнут
    assert client.get("/dedup").json() == []
    assert client.get("/jobs/deadbeef").status_code == 404
