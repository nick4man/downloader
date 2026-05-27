"""Проверка JWT Cloudflare Access (вход по пользователю Cloudflare).

Cloudflare Access кладёт подписанный JWT в заголовок `Cf-Access-Jwt-Assertion`
(и cookie `CF_Authorization`). Проверяем подпись против JWKS команды и `aud`
приложения — доверять «голому» email-заголовку нельзя (демон слушает и на LAN).
"""

from __future__ import annotations

import contextlib

import jwt
from jwt import PyJWKClient

from downloader.config import Config

_clients: dict[str, PyJWKClient] = {}  # кэш JWKS-клиента по team-домену


def _jwks(team_domain: str) -> PyJWKClient:
    client = _clients.get(team_domain)
    if client is None:
        client = PyJWKClient(f"https://{team_domain}/cdn-cgi/access/certs")
        _clients[team_domain] = client
    return client


def verify(jwt_assertion: str | None, config: Config) -> str | None:
    """Вернуть email пользователя при валидном CF-Access JWT, иначе None."""
    if not (jwt_assertion and config.cf_access_team_domain and config.cf_access_aud):
        return None
    data = None
    with contextlib.suppress(Exception):  # любая ошибка проверки → отказ
        key = _jwks(config.cf_access_team_domain).get_signing_key_from_jwt(jwt_assertion).key
        data = jwt.decode(
            jwt_assertion, key, algorithms=["RS256"], audience=config.cf_access_aud
        )
    if data is None:
        return None
    email = data.get("email", "")
    if config.cf_access_emails and email not in config.cf_access_emails:
        return None  # не в allowlist
    return email or "cf-access-user"
