// Theme system: 7 brand colour swatches + light/dark/time-based mode.
// Default is always light + classic (#ccffcc), regardless of OS preference.
// Once the user picks something, it is persisted.

const APP_KEY = "qrmaker";

const COLOR_THEMES = [
  { id: "classic", label: "Classic", hex: "#ccffcc" },
  { id: "not-green-1", label: "Not green 1", hex: "#ffcccc" },
  { id: "not-green-2", label: "Not green 2", hex: "#ccccff" },
  { id: "not-green-3", label: "Not green 3", hex: "#ffffcc" },
  { id: "not-green-4", label: "Not green 4", hex: "#ffccff" },
  { id: "not-green-5", label: "Not green 5", hex: "#ccffff" },
  { id: "really-light-green", label: "Really really light green", hex: "#ffffff" },
];

const STORAGE_KEY_COLOR = `${APP_KEY}.colorTheme`;
const STORAGE_KEY_MODE = `${APP_KEY}.mode`;

// What the user picked. "time" is stored as-is and resolved to light or dark
// on every read, so data-mode itself is only ever "light" or "dark".
const MODE_PREFERENCES = ["light", "dark", "time"];

// Time-based mode: light from LIGHT_FROM_HOUR until LIGHT_UNTIL_HOUR, local
// time, dark the rest of the day. The pre-paint script in index.html's <head>
// repeats these two numbers; keep them in step.
const LIGHT_FROM_HOUR = 7;
const LIGHT_UNTIL_HOUR = 19;

// Old pre-retrofit key and its swatch ids. Read once, then dropped.
const LEGACY_KEY = "qr_theme";
const LEGACY_MAP = {
  classic: "classic",
  pink: "not-green-1",
  lavender: "not-green-2",
  yellow: "not-green-3",
  rose: "not-green-4",
  cyan: "not-green-5",
  white: "really-light-green",
};

function migrateLegacyTheme() {
  const old = localStorage.getItem(LEGACY_KEY);
  if (!old) return;
  if (!localStorage.getItem(STORAGE_KEY_COLOR) && LEGACY_MAP[old]) {
    localStorage.setItem(STORAGE_KEY_COLOR, LEGACY_MAP[old]);
  }
  localStorage.removeItem(LEGACY_KEY);
}

function hexToRgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}

function getStoredColorTheme() {
  return localStorage.getItem(STORAGE_KEY_COLOR) || "classic";
}

function getModePreference() {
  const stored = localStorage.getItem(STORAGE_KEY_MODE);
  return MODE_PREFERENCES.includes(stored) ? stored : "light";
}

function isDaylightHours(date = new Date()) {
  const hour = date.getHours();
  return hour >= LIGHT_FROM_HOUR && hour < LIGHT_UNTIL_HOUR;
}

function resolveMode(preference) {
  if (preference === "time") return isDaylightHours() ? "light" : "dark";
  return preference === "dark" ? "dark" : "light";
}

// The mode on screen right now, never "time".
function getStoredMode() {
  return resolveMode(getModePreference());
}

function applyColorTheme(id) {
  const theme = COLOR_THEMES.find((t) => t.id === id) || COLOR_THEMES[0];
  document.documentElement.setAttribute("data-color-theme", theme.id);
  document.documentElement.style.setProperty("--brand", theme.hex);
  document.documentElement.style.setProperty("--brand-rgb", hexToRgb(theme.hex));
  localStorage.setItem(STORAGE_KEY_COLOR, theme.id);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme.hex);
  return theme;
}

function applyMode(preference) {
  const pref = MODE_PREFERENCES.includes(preference) ? preference : "light";
  const resolved = resolveMode(pref);
  document.documentElement.setAttribute("data-mode", resolved);
  document.documentElement.setAttribute("data-mode-preference", pref);
  localStorage.setItem(STORAGE_KEY_MODE, pref);
  scheduleModeCheck();
  return resolved;
}

/* ---- time-based mode: flip at the boundary ---- */

let modeCheckTimer = null;

function msUntilNextBoundary(now = new Date()) {
  const next = new Date(now);
  const hour = now.getHours();
  if (hour < LIGHT_FROM_HOUR) {
    next.setHours(LIGHT_FROM_HOUR, 0, 0, 0);
  } else if (hour < LIGHT_UNTIL_HOUR) {
    next.setHours(LIGHT_UNTIL_HOUR, 0, 0, 0);
  } else {
    next.setDate(next.getDate() + 1);
    next.setHours(LIGHT_FROM_HOUR, 0, 0, 0);
  }
  return next - now;
}

// One timer, aimed at the next boundary, only while "time" is picked.
function scheduleModeCheck() {
  clearTimeout(modeCheckTimer);
  modeCheckTimer = null;
  if (getModePreference() !== "time") return;
  // A second past the boundary, so the hour has definitely turned over.
  modeCheckTimer = setTimeout(refreshTimeMode, msUntilNextBoundary() + 1000);
}

function refreshTimeMode() {
  if (getModePreference() !== "time") {
    scheduleModeCheck();
    return;
  }
  const before = document.documentElement.getAttribute("data-mode");
  const after = applyMode("time");
  if (before !== after) {
    document.dispatchEvent(
      new CustomEvent("uwu:modechange", { detail: { preference: "time", mode: after } })
    );
  }
}

// Background tabs throttle timers and a sleeping laptop skips them entirely,
// so check again whenever the tab comes back into view.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshTimeMode();
});

function initTheme() {
  migrateLegacyTheme();
  applyColorTheme(getStoredColorTheme());
  applyMode(getModePreference());
}

/* ---- modal wiring ---- */

function buildThemeModal() {
  const grid = document.getElementById("swatchGrid");
  grid.innerHTML = COLOR_THEMES.map(
    (t) => `
      <button class="swatch" data-theme-id="${t.id}" style="--swatch-color:${t.hex}" type="button" aria-label="${t.label}">
        <span class="swatch-dot"></span>
        <span class="swatch-label">${t.label}</span>
      </button>`
  ).join("");

  syncThemeModalState();

  grid.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-theme-id]");
    if (!btn) return;
    applyColorTheme(btn.dataset.themeId);
    syncThemeModalState();
  });

  document.getElementById("modeToggle").addEventListener("click", (e) => {
    // Not "[data-mode]": <html> carries data-mode too, so a click in the gap
    // between buttons would walk up to it and pick the resolved mode.
    const btn = e.target.closest(".mode-btn");
    if (!btn) return;
    applyMode(btn.dataset.mode);
    syncThemeModalState();
  });

  // Time-based crossed a boundary: the page has already flipped, keep the
  // modal and the topbar icon in step with it.
  document.addEventListener("uwu:modechange", syncThemeModalState);
}

function formatHour(hour) {
  return new Date(2000, 0, 1, hour).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function syncThemeModalState() {
  const activeTheme = getStoredColorTheme();
  const activePreference = getModePreference();
  const resolvedMode = resolveMode(activePreference);
  document.querySelectorAll("#swatchGrid .swatch").forEach((el) => {
    el.classList.toggle("active", el.dataset.themeId === activeTheme);
  });
  document.querySelectorAll("#modeToggle .mode-btn").forEach((el) => {
    const pressed = el.dataset.mode === activePreference;
    el.classList.toggle("active", pressed);
    el.setAttribute("aria-pressed", String(pressed));
  });
  const note = document.getElementById("modeNote");
  if (note) {
    note.hidden = activePreference !== "time";
    note.textContent = note.hidden
      ? ""
      : `Light from ${formatHour(LIGHT_FROM_HOUR)} to ${formatHour(LIGHT_UNTIL_HOUR)}, ` +
        `dark the rest of the day. It's ${resolvedMode} right now.`;
  }
  updateThemeButtonIcon();
}

function updateThemeButtonIcon() {
  const span = document.querySelector("#themeBtn [data-icon]");
  span.setAttribute("data-icon", getStoredMode() === "dark" ? "moon" : "sun");
  hydrateIcons(document.getElementById("themeBtn"));
}

function wireModals() {
  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.closeModal));
  });
  document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeModal(backdrop.id);
    });
  });
  document.getElementById("themeBtn").addEventListener("click", () => openModal("themeModal"));
}

initTheme();
hydrateIcons();
updateThemeButtonIcon();
buildThemeModal();
wireModals();
