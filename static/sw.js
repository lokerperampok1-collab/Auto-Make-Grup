const CACHE_NAME = "auto-make-grup-clay-v1";
const ASSETS = [
  "/",
  "/static/index.html",
  "/static/style.css",
  "/static/app.js",
  "/static/standalone_mtproto.js",
  "/static/manifest.json",
  "/static/icon.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || event.request.url.includes("/api/")) {
    return;
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
