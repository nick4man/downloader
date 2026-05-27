# Серверная часть (демон FastAPI) в контейнере. CLI снаружи ходит на host:port.
FROM python:3.13-slim

# Внешние инструменты: aria2 (ускоритель прямых закачек) и ffmpeg/ffprobe
# (HLS→MP4, склейка дорожек). Ставим из apt — на PATH, без рантайм-загрузки.
RUN apt-get update && apt-get install -y --no-install-recommends \
        aria2 ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv — менеджер зависимостей проекта.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV DOWNLOADER_HOST=0.0.0.0 \
    DOWNLOADER_PORT=8765 \
    DOWNLOADER_DOWNLOAD_DIR=/downloads \
    DOWNLOADER_FFMPEG_DIR=/usr/bin \
    XDG_DATA_HOME=/data

EXPOSE 8765
VOLUME ["/downloads", "/data"]

# daemon-serve = foreground-тело демона (uvicorn); процессом управляет Docker.
CMD ["uv", "run", "dl", "daemon-serve"]
