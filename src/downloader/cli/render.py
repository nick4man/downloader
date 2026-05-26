"""Представление: rich-таблицы и прогресс-бары."""

from __future__ import annotations

from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from downloader.models import DownloadJob, JobState, MediaInfo

_STATE_STYLE = {
    JobState.QUEUED: "cyan",
    JobState.RUNNING: "yellow",
    JobState.PAUSED: "blue",
    JobState.COMPLETED: "green",
    JobState.ERROR: "red",
    JobState.CANCELED: "dim",
}


def make_progress() -> Progress:
    """Собрать прогресс-бар для активных закачек."""
    return Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    )


def jobs_table(jobs: list[DownloadJob]) -> Table:
    """Таблица задач для `dl list` / `dl status`."""
    table = Table(title="Задачи")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Состояние")
    table.add_column("Имя")
    table.add_column("Прогресс", justify="right")
    table.add_column("URL", overflow="fold")

    for job in jobs:
        style = _STATE_STYLE.get(job.state, "white")
        table.add_row(
            job.id[:8],
            f"[{style}]{job.state.value}[/{style}]",
            job.filename or "—",
            _progress_str(job),
            job.url,
        )
    return table


def _progress_str(job: DownloadJob) -> str:
    if job.bytes_total:
        pct = 100 * job.bytes_done / job.bytes_total
        return f"{pct:.0f}%"
    if job.bytes_done:
        return f"{job.bytes_done} B"
    return "—"


def _human_size(num: int) -> str:
    """Человекочитаемый размер в бинарных единицах."""
    size = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{num}B"


def formats_table(media: MediaInfo) -> Table:
    """Таблица доступных форматов для `dl formats`."""
    table = Table(title=media.title or media.url)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("EXT")
    table.add_column("Разрешение", justify="right")
    table.add_column("Видео")
    table.add_column("Аудио")
    table.add_column("Размер", justify="right")
    table.add_column("Прим.")

    for f in media.formats:
        res = f"{f.height}p" if f.height else "—"
        size = _human_size(f.filesize) if f.filesize else "—"
        table.add_row(
            f.format_id, f.ext or "—", res, f.vcodec or "—", f.acodec or "—", size, f.note or ""
        )
    return table
