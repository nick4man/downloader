#!/bin/sh
# Точка входа контейнера: освежить yt-dlp (сайты меняются чаще релизов образа),
# затем запустить демон. Обновление не фатально — при офлайне берём версию из образа.
set -e

if [ "${DOWNLOADER_UPDATE_YTDLP:-1}" = "1" ]; then
    echo "[entrypoint] обновляю yt-dlp…"
    uv pip install --upgrade yt-dlp || echo "[entrypoint] не удалось обновить yt-dlp — продолжаю на версии из образа"
fi

exec uv run dl daemon-serve
