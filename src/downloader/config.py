"""Конфигурация менеджера закачек: TOML + XDG-пути."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


def _xdg(env: str, default: Path) -> Path:
    """Вернуть путь из XDG-переменной окружения или дефолт."""
    raw = os.environ.get(env)
    return Path(raw) if raw else default


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "downloader"
DATA_DIR = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / "downloader"
CONFIG_PATH = CONFIG_DIR / "config.toml"
DB_PATH = DATA_DIR / "downloader.db"
COOKIES_PATH = DATA_DIR / "cookies.txt"  # куда сохраняется загруженный cookies.txt


class Config(BaseModel):
    """Пользовательские настройки."""

    download_dir: str = Field(default_factory=lambda: str(Path.home() / "Downloads"))
    max_concurrent: int = 3
    default_quality: int = 1080
    connections: int = 16  # параллельные соединения для aria2
    aria2_path: str | None = None  # None → автоопределение через shutil.which
    host: str = "127.0.0.1"  # адрес демона
    port: int = 8765  # порт демона
    # Origin'ы, которым разрешён CORS (для букмарклета/расширения с чужих сайтов).
    # '*' удобно для личного инструмента; ужесточай списком сайтов при необходимости.
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    cookies_file: str | None = None  # путь к cookies.txt (Netscape); None → COOKIES_PATH
    # Токен доступа: если задан — API требует его (для выставления в интернет/туннель).
    # None → без аутентификации (локальный режим).
    auth_token: str | None = None
    # Cloudflare Access: альтернативный вход по пользователю (проверка JWT).
    cf_access_team_domain: str | None = None  # <team>.cloudflareaccess.com
    cf_access_aud: str | None = None  # Application Audience (AUD) tag приложения
    cf_access_emails: list[str] = Field(default_factory=list)  # allowlist (пусто = любой)

    def dump_toml(self) -> str:
        """Сериализовать в TOML (без сторонних зависимостей)."""
        lines: list[str] = []
        for key, value in self.model_dump().items():
            if value is None:
                continue  # пропускаем незаданные опции
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, list):
                items = ", ".join(f'"{v}"' for v in value)
                lines.append(f"{key} = [{items}]")
            else:
                lines.append(f"{key} = {value}")
        return "\n".join(lines) + "\n"


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Загрузить конфиг: TOML, поверх — переменные окружения (для Docker)."""
    data: dict = {}
    if path.exists():
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    config = Config.model_validate(data)

    # env-оверрайды (DOWNLOADER_*) имеют приоритет — удобно для контейнера.
    config.host = os.environ.get("DOWNLOADER_HOST", config.host)
    config.download_dir = os.environ.get("DOWNLOADER_DOWNLOAD_DIR", config.download_dir)
    if port := os.environ.get("DOWNLOADER_PORT"):
        config.port = int(port)
    if mc := os.environ.get("DOWNLOADER_MAX_CONCURRENT"):
        config.max_concurrent = int(mc)
    if cors := os.environ.get("DOWNLOADER_CORS"):
        config.cors_origins = [o.strip() for o in cors.split(",") if o.strip()]
    config.cookies_file = os.environ.get("DOWNLOADER_COOKIES", config.cookies_file)
    config.auth_token = os.environ.get("DOWNLOADER_TOKEN", config.auth_token)
    config.cf_access_team_domain = os.environ.get(
        "DOWNLOADER_CF_TEAM", config.cf_access_team_domain
    )
    config.cf_access_aud = os.environ.get("DOWNLOADER_CF_AUD", config.cf_access_aud)
    if emails := os.environ.get("DOWNLOADER_CF_EMAILS"):
        config.cf_access_emails = [e.strip() for e in emails.split(",") if e.strip()]
    return config


def effective_cookies(config: Config) -> str | None:
    """Путь к cookies.txt, если файл реально существует (для yt-dlp --cookies)."""
    path = Path(config.cookies_file) if config.cookies_file else COOKIES_PATH
    return str(path) if path.exists() else None


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    """Сохранить конфиг, создав каталог при необходимости."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.dump_toml(), encoding="utf-8")
