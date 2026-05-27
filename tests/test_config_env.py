"""Тесты env-оверрайдов конфига и пути ffmpeg (нужно для Docker)."""

from __future__ import annotations

from pathlib import Path

from downloader import config
from downloader.tools import base


def test_env_overrides_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOWNLOADER_HOST", "0.0.0.0")
    monkeypatch.setenv("DOWNLOADER_PORT", "9999")
    monkeypatch.setenv("DOWNLOADER_DOWNLOAD_DIR", "/downloads")
    monkeypatch.setenv("DOWNLOADER_MAX_CONCURRENT", "7")
    monkeypatch.setenv("DOWNLOADER_CORS", "https://a.com, https://b.com")
    cfg = config.load_config(tmp_path / "absent.toml")  # файла нет → дефолты + env
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9999
    assert cfg.download_dir == "/downloads"
    assert cfg.max_concurrent == 7
    assert cfg.cors_origins == ["https://a.com", "https://b.com"]


def test_ffmpeg_dir_env(monkeypatch) -> None:
    monkeypatch.setenv("DOWNLOADER_FFMPEG_DIR", "/usr/bin")
    assert base.resolve_binary("ffmpeg") == "/usr/bin/ffmpeg"
    assert base.resolve_binary("ffprobe") == "/usr/bin/ffprobe"
