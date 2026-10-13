/*
 * Ride Pulse service worker: makes the app installable and lets it open without a network.
 *
 * - Page loads: network first (always the latest app), falling back to the last cached copy of
 *   the app shell when offline. Every route serves the same index.html, so one copy covers all.
 * - Built assets (/static/app/assets/*): cache first. Their names contain a content hash, so a
 *   cached file can never be stale.
 * - Everything else (the API, WebSockets, map tiles) goes straight to the network: live data
 *   must never come from a cache.
 */
const CACHE = "ride-pulse-v1";
const SHELL = "/__shell";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(SHELL, copy));
          }
          return response;
        })
        .catch(() => caches.match(SHELL).then((cached) => cached || Response.error())),
    );
    return;
  }

  if (url.pathname.startsWith("/static/app/")) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});
