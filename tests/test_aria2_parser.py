"""Тесты разбора прогресса aria2c."""

from __future__ import annotations

import asyncio

from downloader.tools.aria2 import _parse_eta, parse_progress
from downloader.tools.base import iter_lines


def test_parse_progress_full() -> None:
    line = "[#0a3f8e 4.5MiB/19MiB(23%) CN:5 DL:2.3MiB ETA:6s]"
    ev = parse_progress(line, job_id="J")
    assert ev is not None
    assert ev.job_id == "J"
    assert ev.bytes_done == int(4.5 * (1 << 20))
    assert ev.bytes_total == 19 * (1 << 20)
    assert ev.percent == 23.0
    assert ev.speed == int(2.3 * (1 << 20))
    assert ev.eta == 6.0


def test_parse_progress_no_eta() -> None:
    ev = parse_progress("[#x 1.0MiB/2.0MiB(50%) DL:500KiB]")
    assert ev is not None
    assert ev.percent == 50.0
    assert ev.eta is None


def test_parse_progress_non_matching() -> None:
    assert parse_progress("12/05 aria2 will resume download") is None


def test_parse_eta_variants() -> None:
    assert _parse_eta("6s") == 6
    assert _parse_eta("1m30s") == 90
    assert _parse_eta("1h2m") == 3720
    assert _parse_eta(None) is None
    assert _parse_eta("nope") is None


async def test_iter_lines_splits_on_cr_and_lf() -> None:
    # aria2 обновляет прогресс через \r; завершающие сообщения — через \n.
    reader = asyncio.StreamReader()
    reader.feed_data(b"[#1 1MiB/2MiB(50%)]\r[#1 2MiB/2MiB(100%)]\nDownload complete\n")
    reader.feed_eof()
    lines = [line async for line in iter_lines(reader)]
    assert lines == [
        "[#1 1MiB/2MiB(50%)]",
        "[#1 2MiB/2MiB(100%)]",
        "Download complete",
    ]


async def test_iter_lines_buffers_partial_chunk() -> None:
    # Неполный хвост без разделителя должен дождаться EOF и выйти целиком.
    reader = asyncio.StreamReader()
    reader.feed_data(b"[#1 1MiB/2MiB(50%)]\rtail-without-newline")
    reader.feed_eof()
    lines = [line async for line in iter_lines(reader)]
    assert lines == ["[#1 1MiB/2MiB(50%)]", "tail-without-newline"]
