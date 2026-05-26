"""Тесты парсинга машинного прогресса yt-dlp (--progress-template)."""

from __future__ import annotations

from downloader.tools.ytdlp import _parse_dlprog


def test_dlprog_with_total() -> None:
    ev = _parse_dlprog("DLPROG 5000 10000", job_id="J")
    assert ev is not None
    assert ev.job_id == "J"
    assert ev.bytes_done == 5000
    assert ev.bytes_total == 10000
    assert ev.percent == 50.0


def test_dlprog_unknown_total() -> None:
    # HLS: размер может быть неизвестен → total None, percent None.
    ev = _parse_dlprog("DLPROG 5000 NA")
    assert ev is not None
    assert ev.bytes_done == 5000
    assert ev.bytes_total is None
    assert ev.percent is None


def test_dlprog_float_estimate() -> None:
    # total_bytes_estimate приходит float-ом ('132.0') — должен парситься.
    ev = _parse_dlprog("DLPROG 1024 132579480.0")
    assert ev is not None
    assert ev.bytes_done == 1024
    assert ev.bytes_total == 132579480


def test_dlprog_malformed() -> None:
    assert _parse_dlprog("DLPROG") is None
    assert _parse_dlprog("DLPROG x y") is None
