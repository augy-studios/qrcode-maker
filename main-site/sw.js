// Bump on every change to anything this worker serves. It is the whole update
// trigger: the browser only sees a new worker, and the page only shows the
// "new version" bar, when this file's bytes change.
const VERSION = "v9";
const CACHE = `uwuqr-${VERSION}`;

// Survives version bumps: Google Fonts, and the last "My QRs" list per session
// so it still opens offline.
const RUNTIME = "uwuqr-runtime";

const ASSETS = [
  "/",
  "/index.html",
  "/style.css",
  "/script.js",
  "/js/theme.js",
  "/js/icons.js",
  "/js/ui.js",
  "/js/sw-update.js",
  "/qrcode.min.js",
  "/manifest.json",
  "/favicon.ico",
  "/icons/qrmakericon1.png",
  "/images/screenshot_1.png",
  "/images/screenshot_2.png"
];

const FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

// No skipWaiting() here. A new version installs and then waits until the
// reader presses Reload on the update bar (see the message handler).
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) =>
      // Past the HTTP cache, so a new version never precaches old files.
      cache.addAll(ASSETS.map((url) => new Request(url, { cache: "reload" })))
    )
  );
});

// No clients.claim() here either: claiming on activate is doing silently what
// the update bar exists to ask about.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE && key !== RUNTIME)
          .map((key) => caches.delete(key))
      )
    )
  );
});

self.addEventListener("message", (event) => {
  const type = typeof event.data === "string" ? event.data : event.data?.type;

  // The only place either of these is ever called.
  if (type === "skip-waiting") {
    event.waitUntil(self.skipWaiting().then(() => self.clients.claim()));
  }
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith("/api/")) {
      event.respondWith(networkFirst(request));
      return;
    }
    if (request.mode === "navigate") {
      event.respondWith(navigation(request));
      return;
    }
    event.respondWith(precached(request));
    return;
  }

  if (FONT_HOSTS.includes(url.hostname)) {
    event.respondWith(staleWhileRevalidate(request));
  }
});

// Pages come from this version's cache, so the HTML and the scripts it loads
// always belong to the same deploy. Anything not precached goes to the
// network, and offline falls back to the app itself.
async function navigation(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request, { ignoreSearch: true });
  if (cached) return cached;
  try {
    return await fetch(request);
  } catch (err) {
    return (await cache.match("/")) || Response.error();
  }
}

// App files: this version's copy, never refreshed underneath the running page.
// Only the next version's worker brings new ones.
async function precached(request) {
  const cache = await caches.open(CACHE);
  return (await cache.match(request)) || fetch(request);
}

// API reads: fresh when online, the last answer when not.
async function networkFirst(request) {
  const cache = await caches.open(RUNTIME);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    return (await cache.match(request)) || Response.error();
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(RUNTIME);
  const cached = await cache.match(request);
  const fetched = fetch(request)
    .then((response) => {
      if (response.ok || response.type === "opaque") cache.put(request, response.clone());
      return response;
    })
    .catch(() => cached || Response.error());
  return cached || fetched;
}
