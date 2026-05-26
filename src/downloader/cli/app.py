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
from downloader.models import DownloadJob, DownloadKind, JobState, ProgressEvent
from downloader.services.formats import select_format
from downloader.services.resolver import classify
from downloader.services.scrape import extract_urls
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
def run(
    quiet: bool = typer.Option(
        False, "--quiet", "-Q", help="Без живого прогресса — только итог (для скриптов/фона)"
    ),
) -> None:
    """Запустить движок и обработать очередь."""
    try:
        asyncio.run(_run(quiet))
    except KeyboardInterrupt:
        # Состояние running-задач останется в БД; следующий `dl run` их докачает.
        console.print(
            "\n[yellow]Прервано. Состояние сохранено — повторите 'dl run' для докачки.[/yellow]"
        )
        raise typer.Exit(130) from None


async def _run(quiet: bool) -> None:
    config = load_config()
    conn = await connect()
    try:
        engine = Engine(conn, config)
        count = await (engine.run_pending() if quiet else _run_with_progress(engine))
    finally:
        await conn.close()

    if count == 0:
        console.print("[dim]Очередь пуста.[/dim]")
    else:
        console.print(f"[green]Обработано задач: {count}[/green]")


async def _run_with_progress(engine: Engine) -> int:
    """Прогон очереди с живым rich-прогрессом (строка появляется сразу)."""
    progress = render.make_progress()
    tasks: dict[str, int] = {}

    def ui(ev: ProgressEvent) -> None:
        task_id = tasks.get(ev.job_id)
        if task_id is None:
            task_id = progress.add_task(ev.msg or ev.job_id[:8], total=ev.bytes_total)
            tasks[ev.job_id] = task_id
        if ev.msg:  # описание несут только стартовые события, байтовые — нет
            progress.update(task_id, description=ev.msg)
        progress.update(task_id, completed=ev.bytes_done, total=ev.bytes_total)

    with progress:
        return await engine.run_pending(ui)


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


async def _resolve_job(conn, job_id: str) -> DownloadJob:
    """Найти задачу по полному id или однозначному префиксу (как в `dl list`)."""
    job = await jobs_repo.get_job(conn, job_id)
    if job is not None:
        return job
    matches = [j for j in await jobs_repo.list_jobs(conn) if j.id.startswith(job_id)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        console.print(f"[red]Задача '{job_id}' не найдена.[/red]")
    else:
        ids = ", ".join(j.id[:8] for j in matches)
        console.print(f"[red]Префикс '{job_id}' неоднозначен: {ids}[/red]")
    raise typer.Exit(1)


@app.command()
def status(job_id: str | None = typer.Argument(None)) -> None:
    """Показать статус одной задачи или всех."""
    asyncio.run(_status(job_id))


async def _status(job_id: str | None) -> None:
    conn = await connect()
    try:
        if job_id is None:
            jobs = await jobs_repo.list_jobs(conn)
            console.print(render.jobs_table(jobs) if jobs else "[dim]Задач нет.[/dim]")
            return
        job = await _resolve_job(conn, job_id)
        console.print(render.jobs_table([job]))
        if job.error:
            console.print(f"[red]Ошибка:[/red] {job.error}")
    finally:
        await conn.close()


@app.command()
def pause(job_id: str) -> None:
    """Поставить задачу на паузу (движок будет её пропускать)."""
    asyncio.run(_set_state(job_id, JobState.PAUSED, allowed_from={JobState.QUEUED, JobState.ERROR}))


@app.command()
def resume(job_id: str) -> None:
    """Вернуть задачу в очередь."""
    asyncio.run(
        _set_state(
            job_id,
            JobState.QUEUED,
            allowed_from={JobState.PAUSED, JobState.ERROR, JobState.CANCELED},
        )
    )


async def _set_state(job_id: str, target: JobState, *, allowed_from: set[JobState]) -> None:
    conn = await connect()
    try:
        job = await _resolve_job(conn, job_id)
        if job.state not in allowed_from:
            console.print(
                f"[yellow]Нельзя перевести из '{job.state.value}' в '{target.value}'.[/yellow]"
            )
            raise typer.Exit(1)
        await jobs_repo.set_state(conn, job.id, target)
    finally:
        await conn.close()
    console.print(f"[green]{job.id[:8]} → {target.value}[/green]")


@app.command()
def rm(job_id: str) -> None:
    """Удалить задачу из очереди (с незавершёнными артефактами .part/.aria2)."""
    asyncio.run(_rm(job_id))


async def _rm(job_id: str) -> None:
    conn = await connect()
    try:
        job = await _resolve_job(conn, job_id)
        await jobs_repo.delete_job(conn, job.id)
    finally:
        await conn.close()
    _cleanup_partials(job)
    console.print(f"[green]Удалено: {job.id[:8]}[/green]")


def _cleanup_partials(job: DownloadJob) -> None:
    """Снести незавершённые артефакты закачки (готовый файл не трогаем)."""
    if not job.filename:
        return
    target = Path(job.dest_dir) / job.filename
    for suffix in (".part", ".aria2"):
        target.with_suffix(target.suffix + suffix).unlink(missing_ok=True)


@app.command(name="import")
def import_urls(
    file: str,
    dir: str | None = typer.Option(None, "--dir", "-d", help="Каталог сохранения"),
    quality: int | None = typer.Option(
        None, "--quality", "-q", help="Качество для медиа-ссылок, напр. 720"
    ),
) -> None:
    """Импортировать ссылки из файла (список/текст/HTML) в очередь."""
    asyncio.run(_import(file, dir, quality))


async def _import(file: str, dir: str | None, quality: int | None) -> None:
    path = Path(file).expanduser()
    if not path.is_file():
        console.print(f"[red]Файл не найден: {file}[/red]")
        raise typer.Exit(1)

    urls = extract_urls(path.read_text(encoding="utf-8", errors="replace"))
    if not urls:
        console.print("[yellow]URL в файле не найдены.[/yellow]")
        return

    config = load_config()
    dest = str(Path(dir or config.download_dir).expanduser())
    default_q = quality or config.default_quality
    conn = await connect()
    try:
        existing = {j.url for j in await jobs_repo.list_jobs(conn)}
        added = 0
        for url in urls:
            if url in existing:  # уже в очереди — пропускаем
                continue
            kind = classify(url)
            fmt = select_format(default_q) if kind is DownloadKind.MEDIA else None
            await jobs_repo.add_job(conn, DownloadJob(url=url, dest_dir=dest, kind=kind, fmt=fmt))
            added += 1
    finally:
        await conn.close()
    console.print(f"[green]Добавлено {added}[/green] из {len(urls)} (дубли пропущены).")


@app.command()
def dedup() -> None:
    """Найти завершённые задачи с одинаковым содержимым (по SHA256)."""
    asyncio.run(_dedup())


async def _dedup() -> None:
    conn = await connect()
    try:
        jobs = [j for j in await jobs_repo.list_jobs(conn) if j.sha256]
    finally:
        await conn.close()

    groups: dict[str, list[DownloadJob]] = {}
    for job in jobs:
        groups.setdefault(job.sha256 or "", []).append(job)
    dups = {sha: js for sha, js in groups.items() if len(js) > 1}

    if not dups:
        console.print("[dim]Дубликатов не найдено.[/dim]")
        return
    for sha, js in dups.items():
        console.print(f"[yellow]{sha[:12]}…[/yellow] — копий: {len(js)}")
        for job in js:
            console.print(f"  {job.id[:8]}  {job.filename or '—'}  [dim]{job.url}[/dim]")


if __name__ == "__main__":
    app()
