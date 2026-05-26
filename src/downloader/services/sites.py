"""Сайт-специфичные экстракторы («плагины» в духе JDownloader).

Некоторые сайты (зеркала xvideos и пр.) на странице видео отдают прямой
SD-mp4, а реальные качества прячут в HLS-мастере (`setVideoHLS`). yt-dlp через
generic-экстрактор берёт SD; чтобы получить топ-качество, достаём HLS-ссылку
сами и скармливаем её yt-dlp (он развернёт варианты и выберет лучший).

Резолв происходит в момент закачки: в HLS-URL есть `secure=…,<timestamp>` —
токен с истечением, добытый заранее протухнет.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

# Семейство xvideos-плееров (общий html5player API).
_PLAYER_HOSTS = ("xvideos", "xv-ru", "xnxx")

_HLS_RE = re.compile(r"setVideoHLS\('([^']+)'\)")
_HIGH_RE = re.compile(r"setVideoUrlHigh\('([^']+)'\)")
_TITLE_RE = re.compile(r"setVideoTitle\('(.*?)'\)")

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _parse_player(html: str) -> tuple[str, str | None] | None:
    """Достать из HTML (медиа_url, заголовок). HLS-мастер приоритетнее High-mp4."""
    source = _HLS_RE.search(html) or _HIGH_RE.search(html)
    if source is None:
        return None
    title_match = _TITLE_RE.search(html)
    title = title_match.group(1).strip() if title_match else None
    return source.group(1), title


async def resolve_source(url: str) -> tuple[str, str | None] | None:
    """Для поддерживаемого сайта вернуть (медиа_url, заголовок), иначе None.

    Предпочитаем HLS-мастер (топ-качество); если его нет — High-mp4.
    Сетевые ошибки пробрасываем наружу (воркер положит их в job.error).
    """
    host = urlparse(url).hostname or ""
    if not any(h in host for h in _PLAYER_HOSTS):
        return None

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=_UA) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text
    return _parse_player(html)
