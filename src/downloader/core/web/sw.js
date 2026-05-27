// Минимальный service worker — нужен для установки PWA (и share_target).
// Сетевую логику не трогаем: запросы идут как есть (passthrough).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
