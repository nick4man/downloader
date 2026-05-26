"""Тесты извлечения URL из текста."""

from __future__ import annotations

from downloader.services.scrape import extract_urls


def test_plain_list() -> None:
    text = "https://a.com/f.zip\nhttp://b.com/g.bin\n"
    assert extract_urls(text) == ["https://a.com/f.zip", "http://b.com/g.bin"]


def test_strips_trailing_punctuation() -> None:
    # Замыкающие пунктуация и непарная скобка не должны попасть в URL.
    assert extract_urls("(см. https://e.com/page).") == ["https://e.com/page"]
    assert extract_urls("ссылка: https://e.com/x, дальше") == ["https://e.com/x"]


def test_keeps_balanced_parens() -> None:
    # Парные скобки — часть URL (напр. вики-ссылки), их не срезаем.
    url = "https://en.wikipedia.org/wiki/Foo_(bar)"
    assert extract_urls(f"тут {url} конец") == [url]


def test_html_hrefs() -> None:
    html = '<a href="https://a.com/1">x</a> <img src="https://a.com/2.png">'
    assert extract_urls(html) == ["https://a.com/1", "https://a.com/2.png"]


def test_dedup_preserves_order() -> None:
    text = "https://a.com https://b.com https://a.com"
    assert extract_urls(text) == ["https://a.com", "https://b.com"]


def test_no_urls() -> None:
    assert extract_urls("просто текст без ссылок") == []
