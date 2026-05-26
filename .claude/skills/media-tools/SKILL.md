---
name: media-tools
description: Reference patterns for wrapping yt-dlp, ffmpeg, and aria2 in this download manager — quality/format selection, HLS→MP4 conversion, resume, metadata tagging, and dedup. Use when writing or reviewing code that invokes these external binaries.
---

# media-tools

Соглашения по вызову внешних инструментов в этом проекте. Держи флаги и подходы единообразными.

## Общие правила
- Вызывай бинарники через `subprocess` со списком аргументов (не `shell=True`).
- Перед вызовом проверяй наличие бинарника (`shutil.which`) и понятно сообщай, если его нет.
- Парси прогресс/ошибки из stdout/stderr, не глотай коды возврата.

## yt-dlp — парсинг ссылок и качество
- Список доступных форматов: `yt-dlp -F <url>` (или `--list-formats`).
- Метаданные без скачивания: `yt-dlp -J <url>` (JSON в stdout) — используй для извлечения вариантов качества и заголовка.
- Выбор формата: `-f 'bestvideo[height<=?1080]+bestaudio/best'`.
- Имя файла по шаблону: `-o '%(title)s.%(ext)s'`.
- Встраивание метаданных и обложки: `--embed-metadata --embed-thumbnail`.

## ffmpeg — HLS → MP4
- Конвертация без перекодирования (быстро, если кодеки совместимы): `ffmpeg -i input.m3u8 -c copy -bsf:a aac_adtstoasc output.mp4`.
- Перекодирование, только если `-c copy` не подходит.

## aria2 — докачка (resume)
- Возобновляемая загрузка: `aria2c -c -x16 -s16 -d <dir> -o <name> <url>` (`-c` = continue).
- aria2 сам хранит `.aria2` control-файлы рядом — не удаляй их до завершения.

## Дедуп
- Считай хэш по содержимому (например, sha256) уже скачанных файлов и сверяй перед записью.
- Для частично скачанных опирайся на control-файлы aria2, а не на размер.
