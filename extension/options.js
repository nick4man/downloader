const DEFAULT_BASE = "http://127.0.0.1:8765";
const input = document.getElementById("base");

chrome.storage.sync.get({ base: DEFAULT_BASE }, ({ base }) => {
  input.value = base;
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set({ base: input.value.trim() || DEFAULT_BASE }, () => {
    document.getElementById("msg").textContent = "✓ сохранено";
    setTimeout(() => (document.getElementById("msg").textContent = ""), 1500);
  });
});
