# Деплой: Docker + Cloudflare Tunnel + аутентификация

## 1. Токен (обязательно перед выставлением в интернет)
Демон без токена открыт всем, кто знает URL (включая загрузку/чтение cookies).
Задай `DOWNLOADER_TOKEN` — тогда API требует его:

```bash
export DOWNLOADER_TOKEN=$(openssl rand -hex 24)
```

Как клиенты передают токен:
- **Морда**: открой `https://<твой-домен>/?token=<TOKEN>` один раз — сервер
  поставит cookie `dl_token`, дальше всё работает прозрачно (и `/share`, и WebSocket).
- **Расширение**: укажи токен в настройках расширения.
- **Букмарклет**: морда вшивает токен из cookie автоматически (пересоздай закладку
  после входа с токеном).
- **curl**: `-H "Authorization: Bearer $DOWNLOADER_TOKEN"`.

## 2. Запуск в Docker
```bash
DOWNLOAD_DIR=/path/to/Videos DOWNLOADER_TOKEN=$DOWNLOADER_TOKEN \
  docker compose up -d --build
```
Морда локально: http://localhost:8765/?token=$DOWNLOADER_TOKEN

## 3. Cloudflare Tunnel (публичный HTTPS без проброса портов)
Даёт HTTPS-URL — нужно для Android-PWA (share target) и доступа извне.

1. В дашборде **Cloudflare Zero Trust → Networks → Tunnels** создай туннель,
   скопируй его **token**.
2. Public hostname туннеля → сервис `http://downloader:8765`.
3. Запусти с профилем `tunnel`:
   ```bash
   CLOUDFLARE_TUNNEL_TOKEN=<token> DOWNLOADER_TOKEN=$DOWNLOADER_TOKEN \
     docker compose --profile tunnel up -d --build
   ```

## 4. Вход по пользователю Cloudflare Access (вместо/вместе с токеном)
В Zero Trust → Access закрой домен туннеля логином (Google/почта). Демон умеет
**проверять JWT Access** сам (подпись + `aud`), так что доступ открыт, если
пришёл валидный токен **или** валидный Cloudflare-пользователь — оба способа
работают одновременно.

Настрой демону:
```bash
DOWNLOADER_CF_TEAM=<team>.cloudflareaccess.com   # домен команды
DOWNLOADER_CF_AUD=<application-audience-tag>      # AUD из Access-приложения
DOWNLOADER_CF_EMAILS=me@example.com,friend@x.com  # (опц.) allowlist; пусто = любой вошедший
```
Где взять AUD: дашборд Access → твоё приложение → **Application Audience (AUD) Tag**.

Так можно: оставить `DOWNLOADER_TOKEN` для расширения/букмарклета/curl, а вход
с телефона/браузера закрыть логином Cloudflare — оба пути пускают.

## Android
После того как туннель отдаёт HTTPS: открой морду на телефоне (с `?token=`),
«Установить приложение», и в системном «Поделиться» появится downloader.
