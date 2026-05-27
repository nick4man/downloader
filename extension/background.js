// Контекстное меню «отправить в downloader»: POST {url} на /jobs демона.
const DEFAULT_BASE = "http://127.0.0.1:8765";

const MENU = [
  { id: "dl-link", title: "Отправить ссылку в downloader", contexts: ["link"] },
  { id: "dl-media", title: "Отправить медиа в downloader", contexts: ["video", "audio", "image"] },
  { id: "dl-page", title: "Отправить страницу в downloader", contexts: ["page", "selection"] },
];

chrome.runtime.onInstalled.addListener(() => {
  for (const m of MENU) chrome.contextMenus.create(m);
});

chrome.contextMenus.onClicked.addListener(async (info) => {
  const url = info.linkUrl || info.srcUrl || info.pageUrl;
  if (!url) return;
  const { base } = await chrome.storage.sync.get({ base: DEFAULT_BASE });
  try {
    const resp = await fetch(base.replace(/\/$/, "") + "/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    flash(resp.ok ? "✓" : "✗", resp.ok ? "#16a34a" : "#dc2626");
  } catch {
    flash("✗", "#dc2626");
  }
});

// Обратная связь без иконок — бейдж на значке расширения.
function flash(text, color) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2000);
}
