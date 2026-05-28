"""Сайт-специфичные экстракторы («плагины» в духе JDownloader).

Некоторые сайты (зеркала xvideos и пр.) на странице видео отдают прямой
SD-mp4, а реальные качества прячут в HLS-мастере (`setVideoHLS`). yt-dlp через
generic-экстрактор берёт SD; чтобы получить топ-качество, достаём HLS-ссылку
сами и скармливаем её yt-dlp (он развернёт варианты и выберет лучший).

Заодно вытаскиваем из HTML метаданные (заголовок, аплоадер/студия, актёры,
теги, обложка) — у сырого m3u8 их нет, а так они попадут в теги MP4.

Резолв происходит в момент закачки: в HLS-URL есть `secure=…,<timestamp>` —
токен с истечением, добытый заранее протухнет.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

# Семейство xvideos-плееров (общий html5player API).
_PLAYER_HOSTS = ("xvideos", "xv-ru", "xnxx")

_HLS_RE = re.compile(r"setVideoHLS\('([^']+)'\)")
_HIGH_RE = re.compile(r"setVideoUrlHigh\('([^']+)'\)")
_TITLE_RE = re.compile(r"setVideoTitle\('(.*?)'\)")
_UPLOADER_RE = re.compile(r"setUploaderName\('(.*?)'\)")
_TAGS_RE = re.compile(r'href="/tags/[a-z0-9_-]+"[^>]*>([^<]+)</a>', re.I)
_ACTOR_RE = re.compile(r'href="/(?:pornstars|models|profiles)/[a-z0-9_-]+"[^>]*>([^<]+)</a>', re.I)
# Картинка-обложка: og:image или thumbnailUrl из JSON-LD.
_THUMB_RE = re.compile(
    r'(?:property="og:image"\s+content|"thumbnailUrl")["\s:=]+"?(https?://[^"\']+)', re.I
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


@dataclass
class SiteMedia:
    """Источник + метаданные, извлечённые со страницы сайта."""

    media_url: str
    title: str | None = None
    uploader: str | None = None  # студия / канал / автор
    actors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    thumbnail: str | None = None


def _parse_player(html: str) -> SiteMedia | None:
    """Достать из HTML источник (HLS-мастер приоритетнее) и метаданные."""
    source = _HLS_RE.search(html) or _HIGH_RE.search(html)
    if source is None:
        return None
    title = _TITLE_RE.search(html)
    uploader = _UPLOADER_RE.search(html)
    thumb = _THUMB_RE.search(html)
    # Дедуп тегов/актёров с сохранением порядка появления.
    tags = list(dict.fromkeys(t.strip() for t in _TAGS_RE.findall(html) if t.strip()))
    actors = list(dict.fromkeys(a.strip() for a in _ACTOR_RE.findall(html) if a.strip()))
    return SiteMedia(
        media_url=source.group(1),
        title=title.group(1).strip() if title else None,
        uploader=uploader.group(1).strip() if uploader else None,
        actors=actors,
        tags=tags[:20],  # не раздуваем genre километровым списком
        thumbnail=thumb.group(1) if thumb else None,
    )


async def resolve_source(url: str) -> SiteMedia | None:
    """Для поддерживаемого сайта вернуть SiteMedia, иначе None.

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
