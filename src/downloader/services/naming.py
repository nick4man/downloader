"""Формирование и санитизация имён файлов."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

# Символы, недопустимые в именах файлов на распространённых ФС.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_LEN = 200


def sanitize_filename(name: str) -> str:
    """Привести имя к безопасному: убрать запрещённые символы, обрезать длину."""
    name = _ILLEGAL.sub("_", name).strip(" .")
    if len(name) > _MAX_LEN:
        # Сохраняем расширение при обрезке.
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 10:
            stem = stem[: _MAX_LEN - len(ext) - 1]
            name = f"{stem}.{ext}"
        else:
            name = name[:_MAX_LEN]
    return name or "download"


def filename_from_url(url: str) -> str:
    """Вывести имя файла из URL (последний сегмент пути)."""
    path = urlparse(url).path
    last = unquote(path.rsplit("/", 1)[-1]) if path else ""
    return sanitize_filename(last) if last else "download"


def filename_from_content_disposition(header: str | None) -> str | None:
    """Достать имя из заголовка Content-Disposition, если оно там есть."""
    if not header:
        return None
    # filename*=UTF-8''... имеет приоритет над filename="..."
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", header, re.IGNORECASE)
    if m:
        return sanitize_filename(unquote(m.group(1).strip()))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', header, re.IGNORECASE)
    if m:
        return sanitize_filename(m.group(1).strip())
    return None
