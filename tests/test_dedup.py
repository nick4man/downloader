"""Тесты контент-дедупа (SHA256 + реестр file_hashes)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from downloader.services import dedup
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
