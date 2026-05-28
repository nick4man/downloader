"""Тесты сайт-экстрактора плеера xvideos-семейства."""

from __future__ import annotations

import asyncio

from downloader.services import sites
from downloader.services.sites import _parse_player


def test_prefers_hls_master() -> None:
    html = """
    html5player.setVideoTitle('Cool Clip');
    html5player.setUploaderName('BlackedRaw');
    html5player.setVideoUrlLow('https://cdn/x/mp4_sd.mp4?secure=a');
    html5player.setVideoUrlHigh('https://cdn/x/mp4_sd.mp4?secure=a');
    html5player.setVideoHLS('https://hls-cdn/x/hls.m3u8?secure=b');
    <meta property="og:image" content="https://thumb/x.jpg">
    <a href="/pornstars/kali-rose" class="x">Kali Rose</a>
    <a href="/tags/anal" class="is-keyword">anal</a>
    <a href="/tags/teen" class="is-keyword">teen</a>
    """
    m = _parse_player(html)
    assert m.media_url == "https://hls-cdn/x/hls.m3u8?secure=b"  # HLS приоритетнее
    assert m.title == "Cool Clip"
    assert m.uploader == "BlackedRaw"
    assert m.actors == ["Kali Rose"]
    assert m.tags == ["anal", "teen"]
    assert m.thumbnail == "https://thumb/x.jpg"


def test_falls_back_to_high_mp4() -> None:
    html = "html5player.setVideoUrlHigh('https://cdn/x/mp4_hd.mp4');"
    m = _parse_player(html)
    assert m.media_url == "https://cdn/x/mp4_hd.mp4"
    assert m.title is None


def test_no_source() -> None:
    assert _parse_player("<html>нет плеера</html>") is None


def test_resolve_source_ignores_unknown_hosts() -> None:
    # Хост не из семейства плееров → None без сетевого запроса.
    assert asyncio.run(sites.resolve_source("https://example.com/video/1")) is None
