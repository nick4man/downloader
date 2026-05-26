"""Typer-приложение: точка входа `dl`."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from downloader import __version__
from downloader.tools.base import have_binary

app = typer.Typer(
    help="Персональный менеджер закачек (aria2/yt-dlp/ffmpeg).",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# Команды, ещё не реализованные на текущей фазе. Регистрируем заранее,
# чтобы поверхность CLI была видна в `--help`.
_PLANNED: dict[str, str] = {
    "add": "Phase 1",
    "run": "Phase 1",
    "list": "Phase 1",
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
            status = "[green]✓ найден[/green]"
        elif required:
            status = "[red]✗ нет[/red]"
        else:
            status = "[yellow]— нет (фолбэк)[/yellow]"
        table.add_row(name, status, note)

    console.print(table)


def _planned(name: str) -> None:
    console.print(f"[yellow]Команда '{name}' появится в {_PLANNED[name]}.[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def add(url: str) -> None:
    """Добавить ссылку в очередь закачки."""
    _planned("add")


@app.command()
def run() -> None:
    """Запустить движок и обработать очередь."""
    _planned("run")


@app.command(name="list")
def list_jobs() -> None:
    """Показать задачи в очереди."""
    _planned("list")


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
