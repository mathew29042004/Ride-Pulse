/*
 * Ride Pulse service worker: makes the app installable and lets it open without a network.
 *
 * - Page loads: network first (always the latest app), falling back to the last cached copy of
 *   the app shell when offline. Every route serves the same index.html, so one copy covers all.
 * - Built assets (/static/app/assets/*): cache first. Their names contain a content hash, so a
 *   cached file can never be stale.
 * - A few read-only API screens (my profile, my active trip, earnings, quests, statements):
 *   network first, with the last good copy as an offline fallback (marked with an
 *   X-From-Cache header). Cleared on sign-out so a shared phone never shows the last user's data.
 * - Everything else (other API calls, WebSockets, map tiles) goes straight to the network: live
 *   data must never come from a cache.
 */
const CACHE = "ride-pulse-v1";
const API_CACHE = "ride-pulse-api-v1";
const OFFLINE_READS = [
  /^\/api\/v1\/(rider|driver)\/me\/$/,
  /^\/api\/v1\/trips\/active\/$/,
  /^\/api\/v1\/driver\/earnings\//,
  /^\/api\/v1\/driver\/biz\/(quests|statements|vehicle)\/$/,
  /^\/api\/v1\/wallet\/$/,
];

self.addEventListener("message", (event) => {
  if (event.data?.type === "clear-api-cache") event.waitUntil(caches.delete(API_CACHE));
});
const SHELL = "/__shell";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE && key !== API_CACHE).map((key) => caches.delete(key))))
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

  if (OFFLINE_READS.some((pattern) => pattern.test(url.pathname))) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(API_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() =>
          caches.open(API_CACHE).then((cache) =>
            cache.match(request).then((cached) => {
              if (!cached) return Response.error();
              const headers = new Headers(cached.headers);
              headers.set("X-From-Cache", "1");
              return cached.blob().then((body) => new Response(body, { status: cached.status, headers }));
            }),
          ),
        ),
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

// --- Push notifications (trip offers, "driver arrived", ...) ---------------------------------
self.addEventListener("push", (event) => {
  let message = { title: "Ride Pulse", body: "", url: "/", tag: "" };
  try {
    message = { ...message, ...event.data.json() };
  } catch {
    /* not JSON: show the generic title */
  }
  event.waitUntil(
    self.registration.showNotification(message.title, {
      body: message.body,
      tag: message.tag || undefined, // a newer offer replaces the previous one
      renotify: Boolean(message.tag),
      icon: "/static/app/icons/icon-192.png",
      badge: "/static/app/icons/icon-192.png",
      data: { url: message.url },
      vibrate: message.tag === "offer" ? [200, 100, 200, 100, 200] : [100],
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => w.url.startsWith(self.location.origin));
      if (open) return open.focus().then(() => open.navigate(url));
      return self.clients.openWindow(url);
    }),
  );
});
