const DEFAULT_BASE = "http://127.0.0.1:8765";
const input = document.getElementById("base");
const tokenInput = document.getElementById("token");

chrome.storage.sync.get({ base: DEFAULT_BASE, token: "" }, ({ base, token }) => {
  input.value = base;
  tokenInput.value = token;
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set(
    { base: input.value.trim() || DEFAULT_BASE, token: tokenInput.value.trim() },
    () => {
      document.getElementById("msg").textContent = "✓ сохранено";
      setTimeout(() => (document.getElementById("msg").textContent = ""), 1500);
    },
  );
});
