"""Тесты проверки Cloudflare Access (без сетевых вызовов)."""

from __future__ import annotations

from downloader.config import Config
from downloader.core import cf_access


def test_disabled_when_not_configured() -> None:
    # team/aud не заданы → CF-Access не активен, любой JWT отвергается.
    assert cf_access.verify("a.b.c", Config()) is None


def test_none_without_jwt() -> None:
    cfg = Config(cf_access_team_domain="team.cloudflareaccess.com", cf_access_aud="aud123")
    assert cf_access.verify(None, cfg) is None  # нет JWT → None (без обращения к JWKS)
