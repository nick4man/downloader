"""Тесты неймингов."""

from __future__ import annotations

from downloader.services.naming import (
    filename_from_content_disposition,
    filename_from_url,
    sanitize_filename,
)


def test_filename_from_url() -> None:
    assert filename_from_url("https://e.com/path/video.mp4?x=1") == "video.mp4"
    assert filename_from_url("https://e.com/%D1%84%D0%B0%D0%B9%D0%BB.bin") == "файл.bin"


def test_filename_from_url_empty() -> None:
    assert filename_from_url("https://e.com/") == "download"


def test_sanitize_removes_illegal() -> None:
    assert sanitize_filename("a/b:c*?.txt") == "a_b_c__.txt"
    assert sanitize_filename("") == "download"


def test_content_disposition() -> None:
    assert filename_from_content_disposition('attachment; filename="r.zip"') == "r.zip"
    assert filename_from_content_disposition("attachment; filename*=UTF-8''%C3%A9.pdf") == "é.pdf"
    assert filename_from_content_disposition(None) is None
