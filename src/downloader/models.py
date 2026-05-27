"""Доменные модели менеджера закачек (pydantic v2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobState(StrEnum):
    """Состояние задачи в очереди."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELED = "canceled"


class DownloadKind(StrEnum):
    """Тип ссылки — определяет, каким загрузчиком качать."""

    DIRECT = "direct"  # прямой файл → aria2/http
    MEDIA = "media"  # страница с медиа → yt-dlp
    HLS = "hls"  # m3u8-поток → ffmpeg


class Engine(StrEnum):
    """Бэкенд, выполняющий загрузку."""

    ARIA2 = "aria2"
    HTTP = "http"
    YTDLP = "ytdlp"
    FFMPEG = "ffmpeg"


class Format(BaseModel):
    """Один доступный формат медиа (из вывода yt-dlp)."""

    format_id: str
    ext: str | None = None
    height: int | None = None
    vcodec: str | None = None
    acodec: str | None = None
    filesize: int | None = None
    tbr: float | None = None  # суммарный битрейт, кбит/с
    note: str | None = None


class MediaInfo(BaseModel):
    """Метаданные медиа, полученные через `yt-dlp -J`."""

    url: str
    title: str | None = None
    uploader: str | None = None
    duration: float | None = None
    thumbnail: str | None = None
    formats: list[Format] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class ProgressEvent(BaseModel):
    """Снимок прогресса одной задачи (генерируется воркером)."""

    job_id: str
    bytes_done: int = 0
    bytes_total: int | None = None
    speed: float | None = None  # байт/с
    eta: float | None = None  # секунды
    percent: float | None = None
    msg: str | None = None


class DownloadJob(BaseModel):
    """Задача на закачку — основная сущность, хранимая в SQLite."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    url: str
    kind: DownloadKind = DownloadKind.DIRECT
    dest_dir: str
    filename: str | None = None
    fmt: str | None = None  # выбранный format_id / -f строка
    engine: Engine | None = None
    state: JobState = JobState.QUEUED
    bytes_done: int = 0
    bytes_total: int | None = None
    sha256: str | None = None
    error: str | None = None
    position: int = 0  # порядок в очереди (для ручной сортировки)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
