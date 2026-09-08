// Service worker for the Chennai 22K Gold PWA.
//
// Strategy: network-first for everything (app shell and data/*.json
// alike). Always try the network so the shell and the rate data are
// as fresh as possible; only fall back to the cache when the network
// request fails (offline, or a network error). On a successful
// network response, the cache is updated so that fallback stays
// reasonably current.
//
// Bump CACHE_NAME whenever you want to force old cached responses to
// be dropped (e.g. after a shell redesign) -- activate() clears any
// cache that doesn't match the current name.

const CACHE_NAME = "gold22k-shell-v5";

const SHELL_FILES = [
  "./",
  "index.html",
  "manifest.webmanifest",
  "icon.svg",
  "icon-192.png",
  "icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    return;
  }

  event.respondWith(networkFirst(request));
});

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request, { ignoreSearch: true });
    if (cached) {
      return cached;
    }

    // Nothing cached either -- for a navigation request, fall back to
    // the cached app shell so the user still sees something usable
    // instead of a browser error page.
    if (request.mode === "navigate") {
      const shell = await caches.match("index.html", { ignoreSearch: true });
      if (shell) {
        return shell;
      }
    }

    throw err;
  }
}

// --- Target Price Alarm Watchdog & Background Sync Bridge ---
self.addEventListener("sync", (event) => {
  if (event.tag === "gold-rate-sync" || event.tag === "check-gold-price") {
    event.waitUntil(syncLiveRateAndNotify());
  }
});

self.addEventListener("periodicsync", (event) => {
  if (event.tag === "gold-rate-sync" || event.tag === "check-gold-price") {
    event.waitUntil(syncLiveRateAndNotify());
  }
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow("./");
    })
  );
});

async function syncLiveRateAndNotify() {
  try {
    const res = await fetch("data/live.json", { cache: "no-store" });
    if (!res || !res.ok) return;
    const liveData = await res.json();
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    clients.forEach((client) => {
      client.postMessage({ type: "LIVE_RATE_HYDRATED", live: liveData, source: "background-sync" });
    });
  } catch (_) {}
}
