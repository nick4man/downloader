"""Синхронный HTTP-клиент к демону (CLI ↔ FastAPI)."""

from __future__ import annotations

from typing import Any

import httpx

from downloader.config import Config, load_config


def base_url(config: Config | None = None) -> str:
    cfg = config or load_config()
    return f"http://{cfg.host}:{cfg.port}"


def is_up(config: Config | None = None) -> bool:
    """Проверить, отвечает ли демон (короткий health-пинг)."""
    try:
        r = httpx.get(base_url(config) + "/health", timeout=1.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _request(method: str, path: str, **kwargs: Any) -> Any:
    """Выполнить запрос к демону; вернуть JSON или поднять с понятным текстом."""
    try:
        r = httpx.request(method, base_url() + path, timeout=30.0, **kwargs)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"демон недоступен: {exc}") from None
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith(
            "application/json"
        ) else r.text
        raise RuntimeError(detail)
    return r.json()


def add(url: str, dir: str | None = None, quality: int | None = None) -> dict:
    return _request("POST", "/jobs", json={"url": url, "dir": dir, "quality": quality})


def import_urls(urls: list[str], dir: str | None = None, quality: int | None = None) -> dict:
    return _request("POST", "/jobs/import", json={"urls": urls, "dir": dir, "quality": quality})


def list_jobs() -> list[dict]:
    return _request("GET", "/jobs")


def get_job(job_id: str) -> dict:
    return _request("GET", f"/jobs/{job_id}")


def pause(job_id: str) -> dict:
    return _request("POST", f"/jobs/{job_id}/pause")


def resume(job_id: str) -> dict:
    return _request("POST", f"/jobs/{job_id}/resume")


def remove(job_id: str) -> dict:
    return _request("DELETE", f"/jobs/{job_id}")


def rename(job_id: str, filename: str) -> dict:
    return _request("POST", f"/jobs/{job_id}/rename", json={"filename": filename})


def dedup() -> list[dict]:
    return _request("GET", "/dedup")


def shutdown() -> dict:
    return _request("POST", "/shutdown")
