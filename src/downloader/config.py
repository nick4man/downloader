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


class Config(BaseModel):
    """Пользовательские настройки."""

    download_dir: str = Field(default_factory=lambda: str(Path.home() / "Downloads"))
    max_concurrent: int = 3
    default_quality: int = 1080
    connections: int = 16  # параллельные соединения для aria2
    aria2_path: str | None = None  # None → автоопределение через shutil.which
    host: str = "127.0.0.1"  # адрес демона
    port: int = 8765  # порт демона

    def dump_toml(self) -> str:
        """Сериализовать в TOML (без сторонних зависимостей)."""
        lines: list[str] = []
        for key, value in self.model_dump().items():
            if value is None:
                continue  # пропускаем незаданные опции
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            else:
                lines.append(f"{key} = {value}")
        return "\n".join(lines) + "\n"


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Загрузить конфиг; при отсутствии вернуть дефолтный."""
    if not path.exists():
        return Config()
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return Config.model_validate(data)


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    """Сохранить конфиг, создав каталог при необходимости."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.dump_toml(), encoding="utf-8")
