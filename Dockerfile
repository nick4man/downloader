# Серверная часть (демон FastAPI) в контейнере. CLI снаружи ходит на host:port.
FROM python:3.13-slim

# Внешние инструменты: aria2 (ускоритель прямых закачек) и ffmpeg/ffprobe
# (HLS→MP4, склейка дорожек). Ставим из apt — на PATH, без рантайм-загрузки.
RUN apt-get update && apt-get install -y --no-install-recommends \
        aria2 ffmpeg ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# uv — менеджер зависимостей проекта.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

ENV DOWNLOADER_HOST=0.0.0.0 \
    DOWNLOADER_PORT=8765 \
    DOWNLOADER_DOWNLOAD_DIR=/downloads \
    DOWNLOADER_FFMPEG_DIR=/usr/bin \
    DOWNLOADER_UPDATE_YTDLP=1 \
    XDG_DATA_HOME=/data

EXPOSE 8765
VOLUME ["/downloads", "/data"]

# Живость по API, а не «процесс есть» — основа для restart/rolling-деплоя.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8765/health || exit 1

# entrypoint: освежает yt-dlp, затем запускает foreground-тело демона (uvicorn).
ENTRYPOINT ["/app/docker/entrypoint.sh"]
