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

from downloader.models import DownloadJob, JobState

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
