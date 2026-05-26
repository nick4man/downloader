"""Дымовые тесты Phase 0: пакет импортируется, модели и конфиг работают."""

from __future__ import annotations

from pathlib import Path

from downloader import __version__
from downloader.config import Config, load_config, save_config
from downloader.models import DownloadJob, DownloadKind, JobState


def test_version() -> None:
    assert __version__


def test_job_defaults() -> None:
    job = DownloadJob(url="https://example.com/file.bin", dest_dir="/tmp")
    assert job.state is JobState.QUEUED
    assert job.kind is DownloadKind.DIRECT
    assert len(job.id) == 32  # uuid4 hex
    assert job.bytes_done == 0


def test_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    cfg = Config(max_concurrent=5, default_quality=720, download_dir=str(tmp_path))
    save_config(cfg, path)
    assert path.exists()

    loaded = load_config(path)
    assert loaded.max_concurrent == 5
    assert loaded.default_quality == 720
    assert loaded.download_dir == str(tmp_path)


def test_config_missing_returns_defaults(tmp_path: Path) -> None:
    loaded = load_config(tmp_path / "nope.toml")
    assert loaded.max_concurrent == 3
