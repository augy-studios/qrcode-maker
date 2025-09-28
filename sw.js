/* Service Worker: offline cache + share target GET handling */
const CACHE = 'qr-maker-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/styles.css',
  '/script.js',
  '/manifest.json',
  '/qrmakericon1.png',
  '/favicon.ico',
  'https://cdn.jsdelivr.net/npm/qrcode-generator/qrcode.js'
];
self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await c.addAll(ASSETS);
    self.skipWaiting();
  })());
});
self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    self.clients.claim();
  })());
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Handle share target GET (query params already parsed by page)
  if (url.pathname === '/' && url.searchParams.has('share-target')) {
    // Network-first so the app loads fresh if online, else fallback to cache
    e.respondWith((async () => {
      try {
        return await fetch(e.request);
      } catch {
        const c = await caches.open(CACHE);
        return (await c.match('/index.html')) || Response.error();
      }
    })());
    return;
  }
  // Cache-first for app shell
  e.respondWith((async () => {
    const c = await caches.open(CACHE);
    const hit = await c.match(e.request, {
      ignoreSearch: true
    });
    if (hit) return hit;
    try {
      const net = await fetch(e.request);
      // Cache same-origin GET requests for future offline use
      if (e.request.method === 'GET' && url.origin === self.location.origin) c.put(e.request, net.clone());
      return net;
    } catch {
      // Offline fallback to index.html for navigation
      if (e.request.mode === 'navigate') return (await c.match('/index.html')) || Response.error();
      throw new Error('offline');
    }
  })());
});