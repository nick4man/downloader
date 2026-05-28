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


def test_auth_token_gates_api(monkeypatch) -> None:
    monkeypatch.setenv("DOWNLOADER_TOKEN", "secret")

    async def mem_connect(*_a, **_k):
        return await connect(":memory:")

    async def noop_run_job(conn, job, *_a, **_k):
        await jobs_repo.set_state(conn, job.id, JobState.COMPLETED)

    monkeypatch.setattr("downloader.core.api.connect", mem_connect)
    monkeypatch.setattr("downloader.core.scheduler.run_job", noop_run_job)
    from downloader.core.api import app

    with TestClient(app) as c:
        assert c.get("/health").status_code == 200  # публичный
        assert c.get("/jobs").status_code == 401  # без токена — закрыто
        ok = c.get("/jobs", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200
        assert c.get("/jobs?token=secret").status_code == 200  # ?token → cookie
        # навигация (share с телефона) без токена → редирект в приложение, не 401
        c.cookies.clear()  # ?token выше поставил cookie — сбрасываем для чистоты
        nav = c.get(
            "/share?text=https://e.com/x",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert nav.status_code == 303


def test_cors_allows_cross_origin(client) -> None:
    # Букмарклет/расширение шлют с чужого origin — нужен CORS-заголовок.
    r = client.post(
        "/jobs", json={"url": "https://e.com/f.zip"}, headers={"Origin": "https://youtube.com"}
    )
    assert r.headers.get("access-control-allow-origin") in ("*", "https://youtube.com")


def test_cookies_upload_status_delete(client, monkeypatch, tmp_path) -> None:
    import downloader.core.api as api

    monkeypatch.setattr(api, "COOKIES_PATH", tmp_path / "cookies.txt")
    assert client.get("/cookies").json()["present"] is False
    r = client.post("/cookies", content=b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\n")
    assert r.json()["ok"] is True and r.json()["bytes"] > 0
    assert client.get("/cookies").json()["present"] is True
    client.delete("/cookies")
    assert client.get("/cookies").json()["present"] is False


def test_reload(client) -> None:
    r = client.post("/reload").json()
    assert r["ok"] is True
    assert "max_concurrent" in r


def test_websocket_streams_jobs(client) -> None:
    client.post("/jobs", json={"url": "https://e.com/f.zip"})
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()  # первый снимок приходит сразу
        assert isinstance(data, list)
        assert any(j["url"] == "https://e.com/f.zip" for j in data)


def test_share_target_adds_job(client) -> None:
    # Android-шаринг кладёт ссылку в text — должны её извлечь и поставить в очередь.
    r = client.get("/share", params={"text": "смотри https://youtu.be/abc крутое"})
    assert r.status_code == 200 and "Отправлено" in r.text  # страница-подтверждение
    assert any("youtu.be/abc" in j["url"] for j in client.get("/jobs").json())
    # путь iOS-шортката: ссылка в параметре url
    client.get("/share", params={"url": "https://vimeo.com/12345"})
    assert any("vimeo.com/12345" in j["url"] for j in client.get("/jobs").json())


def test_audio_job(client) -> None:
    j = client.post("/jobs", json={"url": "https://youtube.com/watch?v=x", "audio": True}).json()
    assert j["audio"] is True
    assert j["fmt"] is None  # для аудио -f не нужен (yt-dlp -x)


def test_config_get_put(client, monkeypatch) -> None:
    monkeypatch.setattr("downloader.core.api.save_config", lambda *a, **k: None)  # не писать файл
    c = client.get("/config").json()
    assert "download_dir" in c and "max_concurrent" in c
    assert client.put("/config", json={"default_quality": 480, "max_concurrent": 5}).json()["ok"]
    assert client.get("/config").json()["default_quality"] == 480


def test_pwa_assets_served(client) -> None:
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and "share_target" in m.text
    assert client.get("/sw.js").status_code == 200
    assert client.get("/icon.svg").headers["content-type"].startswith("image/svg")


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


def test_export_jobs(client) -> None:
    client.post("/jobs", json={"url": "https://e.com/a.zip"})
    client.post("/jobs", json={"url": "https://e.com/b.zip"})
    r = client.get("/jobs/export")
    assert r.status_code == 200
    assert "a.zip" in r.text and "b.zip" in r.text
    assert "attachment" in r.headers["content-disposition"]


def test_clear_by_state_all(client) -> None:
    for x in "abc":
        client.post("/jobs", json={"url": f"https://e.com/{x}.zip"})
    assert client.delete("/jobs?state=all").json()["removed"] >= 3
    assert client.get("/jobs").json() == []


def test_reorder_endpoint(client) -> None:
    a = client.post("/jobs", json={"url": "https://e.com/a.zip"}).json()["id"]
    b = client.post("/jobs", json={"url": "https://e.com/b.zip"}).json()["id"]
    client.post("/jobs/reorder", json={"ids": [b, a]})  # drag-and-drop порядок
    assert [j["id"] for j in client.get("/jobs").json()] == [b, a]


def test_import_dedup_404(client) -> None:
    res = client.post("/jobs/import", json={"urls": ["https://a.com/1", "https://a.com/1"]}).json()
    assert res == {"added": 1, "total": 2}  # дубль в списке схлопнут
    assert client.get("/dedup").json() == []
    assert client.get("/jobs/deadbeef").status_code == 404
