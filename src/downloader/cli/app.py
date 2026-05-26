"""Typer-приложение: точка входа `dl`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from downloader import __version__
from downloader.cli import render
from downloader.config import load_config
from downloader.core.engine import Engine
from downloader.models import DownloadJob, DownloadKind, ProgressEvent
from downloader.services.formats import select_format
from downloader.services.resolver import classify
from downloader.store import jobs_repo
from downloader.store.db import connect
from downloader.tools import ytdlp
from downloader.tools.base import have_binary

app = typer.Typer(
    help="Персональный менеджер закачек (aria2/yt-dlp/ffmpeg).",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# Команды, ещё не реализованные на текущей фазе.
_PLANNED: dict[str, str] = {
    "status": "Phase 4",
    "pause": "Phase 4",
    "resume": "Phase 4",
    "rm": "Phase 4",
}


@app.command()
def version() -> None:
    """Показать версию."""
    console.print(f"downloader {__version__}")


@app.command()
def doctor() -> None:
    """Проверить наличие внешних инструментов."""
    table = Table(title="Внешние инструменты")
    table.add_column("Инструмент")
    table.add_column("Статус")
    table.add_column("Примечание")

    checks = [
        ("yt-dlp", "обязателен для медиа", True),
        ("ffmpeg", "обязателен для HLS→MP4", True),
        ("ffprobe", "метаданные/проверка", True),
        ("aria2c", "опционально (ускоритель)", False),
    ]
    for name, note, required in checks:
        ok = have_binary(name)
        if ok:
            status_text = "[green]✓ найден[/green]"
        elif required:
            status_text = "[red]✗ нет[/red]"
        else:
            status_text = "[yellow]— нет (фолбэк)[/yellow]"
        table.add_row(name, status_text, note)

    console.print(table)


@app.command()
def add(
    url: str,
    dir: str | None = typer.Option(None, "--dir", "-d", help="Каталог сохранения"),
    quality: int | None = typer.Option(
        None, "--quality", "-q", help="Желаемое качество видео, напр. 720 (для медиа)"
    ),
) -> None:
    """Добавить ссылку в очередь закачки."""
    asyncio.run(_add(url, dir, quality))


async def _add(url: str, dir: str | None, quality: int | None) -> None:
    config = load_config()
    dest = dir or config.download_dir
    kind = classify(url)
    # Для медиа сразу фиксируем -f селектор по желаемому качеству; для прямых не нужно.
    fmt = select_format(quality or config.default_quality) if kind is DownloadKind.MEDIA else None
    job = DownloadJob(url=url, dest_dir=str(Path(dest).expanduser()), kind=kind, fmt=fmt)
    conn = await connect()
    try:
        await jobs_repo.add_job(conn, job)
    finally:
        await conn.close()
    console.print(f"Добавлено: [dim]{job.id[:8]}[/dim] ({kind.value}) → {url}")


@app.command()
def formats(url: str) -> None:
    """Показать доступные форматы медиа-ссылки (yt-dlp -J)."""
    asyncio.run(_formats(url))


async def _formats(url: str) -> None:
    try:
        media = await ytdlp.probe(url)
    except Exception as exc:  # noqa: BLE001 — показываем понятную ошибку, не трейсбек
        console.print(f"[red]Не удалось получить форматы: {exc}[/red]")
        raise typer.Exit(1) from None
    console.print(render.formats_table(media))


@app.command()
def run() -> None:
    """Запустить движок и обработать очередь."""
    asyncio.run(_run())


async def _run() -> None:
    config = load_config()
    conn = await connect()
    try:
        engine = Engine(conn, config)
        progress = render.make_progress()
        tasks: dict[str, int] = {}

        def ui(ev: ProgressEvent) -> None:
            if ev.job_id not in tasks:
                tasks[ev.job_id] = progress.add_task(ev.job_id[:8], total=ev.bytes_total)
            progress.update(tasks[ev.job_id], completed=ev.bytes_done, total=ev.bytes_total)

        with progress:
            count = await engine.run_pending(ui)
    finally:
        await conn.close()

    if count == 0:
        console.print("[dim]Очередь пуста.[/dim]")
    else:
        console.print(f"[green]Обработано задач: {count}[/green]")


@app.command(name="list")
def list_jobs() -> None:
    """Показать задачи в очереди."""
    jobs = asyncio.run(_list())
    if not jobs:
        console.print("[dim]Задач нет.[/dim]")
        return
    console.print(render.jobs_table(jobs))


async def _list() -> list[DownloadJob]:
    conn = await connect()
    try:
        return await jobs_repo.list_jobs(conn)
    finally:
        await conn.close()


def _planned(name: str) -> None:
    console.print(f"[yellow]Команда '{name}' появится в {_PLANNED[name]}.[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def status(job_id: str | None = typer.Argument(None)) -> None:
    """Показать статус задачи (или всех)."""
    _planned("status")


@app.command()
def pause(job_id: str) -> None:
    """Поставить задачу на паузу."""
    _planned("pause")


@app.command()
def resume(job_id: str) -> None:
    """Возобновить задачу."""
    _planned("resume")


@app.command()
def rm(job_id: str) -> None:
    """Удалить задачу из очереди."""
    _planned("rm")


if __name__ == "__main__":
    app()
