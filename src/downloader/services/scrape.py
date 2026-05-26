"""Извлечение URL из произвольного текста (плейн-список, текст, HTML).

Используется командой `dl import <файл>`: читаем файл как текст и вытаскиваем
все http(s)-ссылки, чтобы добавить их в очередь пачкой.
"""

from __future__ import annotations

import re

# URL до первого пробела/кавычки/угловой скобки — это и границы HTML-атрибута.
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_TRAILING_PUNCT = ".,;:!?"
# Закрывающую скобку срезаем, только если она непарная (часть мусора, не URL).
_BRACKETS = ((")", "("), ("]", "["), ("}", "{"))


def _trim(url: str) -> str:
    """Снять с конца URL замыкающую пунктуацию и непарные закрывающие скобки."""
    url = url.rstrip(_TRAILING_PUNCT)
    changed = True
    while changed:
        changed = False
        for close, opn in _BRACKETS:
            if url.endswith(close) and url.count(opn) < url.count(close):
                url = url[:-1].rstrip(_TRAILING_PUNCT)
                changed = True
    return url


def extract_urls(text: str) -> list[str]:
    """Найти в тексте все http(s)-URL и вернуть их БЕЗ дублей, в порядке появления.

    Args:
        text: содержимое файла — список ссылок построчно, обычный текст
            или HTML (тогда ссылки сидят в href="..."/src="...").

    Returns:
        Список уникальных URL в порядке первого появления.
    """
    # dict сохраняет порядок вставки — так дедупим, не теряя очерёдность.
    found: dict[str, None] = {}
    for match in _URL_RE.finditer(text):
        url = _trim(match.group(0))
        if url:
            found.setdefault(url, None)
    return list(found)
