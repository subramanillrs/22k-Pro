// Service worker for the Chennai 22K Gold PWA.
//
// Strategy:
// 1. Data requests (data/*.json): Fast network-first with a 2500ms timeout.
//    Always bypasses the browser/HTTP disk cache using both `cache: "no-store"`
//    and a cache-busting query parameter `?_cb=Date.now()`. If network succeeds,
//    updates the cache in the background. If network takes > 2500ms or fails (offline),
//    falls back immediately to the cached response.
// 2. Navigation requests (mode === 'navigate' / index.html): Network-first with a
//    2000ms timeout so fresh HTML is served when connected, falling back to cached
//    app shell when offline or slow.
// 3. Static shell assets: Network-first with cache fallback.
// 4. Lifecycle: `self.skipWaiting()` and `self.clients.claim()` ensure instant
//    activation without waiting for tabs/PWA restart.

const CACHE_NAME = "gold22k-shell-v7";

const SHELL_FILES = [
  "./",
  "index.html",
  "manifest.webmanifest",
  "icon.svg",
  "icon-192.png",
  "icon-512.png",
];

self.addEventListener("install", (event) => {
  // Activate worker immediately without waiting for existing clients to close
  self.skipWaiting();
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then(async (cache) => {
        try {
          await cache.addAll(SHELL_FILES);
        } catch (err) {
          console.warn("Precache failed partially, attempting individual caching:", err);
          await Promise.all(
            SHELL_FILES.map((file) =>
              cache.add(file).catch((e) => console.warn("Failed caching shell file:", file, e))
            )
          );
        }
      })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    Promise.all([
      // Claim clients immediately so this SW controls all open pages
      self.clients.claim(),
      // Purge obsolete caches
      caches
        .keys()
        .then((keys) =>
          Promise.all(
            keys
              .filter((key) => key !== CACHE_NAME)
              .map((key) => caches.delete(key))
          )
        ),
    ])
  );
});

// Check if request is for rate or analytical data
function isDataRequest(url) {
  const p = url.pathname;
  return (
    p.includes("/data/") ||
    p.endsWith("live.json") ||
    p.endsWith("bootstrap.json") ||
    p.endsWith("signals.json") ||
    p.endsWith("monitoring_windows.json") ||
    p.endsWith(".json")
  );
}

// Check if request is a top-level page navigation
function isNavigationRequest(request, url) {
  return (
    request.mode === "navigate" ||
    url.pathname.endsWith("/index.html") ||
    url.pathname === "/" ||
    url.pathname.endsWith("/")
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    return;
  }

  // Fast network-first with cache-busting & timeout for live and bootstrap data
  if (isDataRequest(url)) {
    event.respondWith(handleDataRequest(event, request, url));
    return;
  }

  // Fast network-first with timeout for navigation requests (index.html shell)
  if (isNavigationRequest(request, url)) {
    event.respondWith(handleNavigationRequest(event, request, url));
    return;
  }

  // Default network-first with cache fallback for other static assets (icons, manifest, etc.)
  event.respondWith(defaultNetworkFirst(request));
});

/**
 * Handles data requests (data/live.json, data/bootstrap.json, etc.):
 * - Always bypasses HTTP disk cache using `cache: "no-store"` and `?_cb=Date.now()`.
 * - Fast network-first with timeout.
 * - Updates cache in the background upon successful fetch.
 * - Broadcasts fresh rate payload to client windows.
 * - Falls back to cache on failure or if network exceeds timeout.
 */
async function handleDataRequest(event, request, url) {
  const fetchUrl = new URL(request.url);
  fetchUrl.searchParams.set("_cb", Date.now().toString());

  let cacheUpdatePromise = null;

  const networkPromise = (async () => {
    const response = await fetch(fetchUrl.toString(), {
      cache: "no-store",
      headers: request.headers,
    });

    if (response && response.ok) {
      const responseToCache = response.clone();
      cacheUpdatePromise = (async () => {
        try {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(request, responseToCache.clone());
          await cache.put(url.pathname, responseToCache.clone());

          // Broadcast fresh data to all open windows so UI updates instantly
          if (url.pathname.includes("live.json")) {
            const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
            const freshJson = await responseToCache.json().catch(() => null);
            if (freshJson) {
              for (const client of clients) {
                client.postMessage({ type: "LIVE_DATA_REFRESHED", payload: freshJson });
              }
            }
          }
        } catch (e) {
          console.warn("Background cache update failed for data:", e);
        }
      })();
      event.waitUntil(cacheUpdatePromise);
    }
    return response;
  })();

  const timeoutPromise = new Promise((_, reject) =>
    setTimeout(() => reject(new Error("DATA_NETWORK_TIMEOUT_2500MS")), 2500)
  );

  try {
    const networkResponse = await Promise.race([networkPromise, timeoutPromise]);
    if (networkResponse && networkResponse.ok) {
      return networkResponse;
    }
    throw new Error("DATA_RESPONSE_NOT_OK");
  } catch (err) {
    // Timeout (> 2500ms) or network error: fall back to cache
    const cached =
      (await caches.match(request, { ignoreSearch: true })) ||
      (await caches.match(url.pathname, { ignoreSearch: true })) ||
      (await caches.match(url.pathname.replace(/^\//, ""), { ignoreSearch: true }));

    if (cached) {
      return cached;
    }

    // If cache is empty (first run), await network response directly
    return await networkPromise;
  }
}

/**
 * Handles navigation requests (index.html / root):
 * - Network-first with cache-busting & 2500ms timeout.
 * - Always bypasses HTTP disk cache using `cache: "no-store"` and `?_nav_cb=Date.now()`.
 * - Fresh index.html served when connected.
 * - Falls back to cached shell if offline or if network takes > 2500ms.
 * - Updates shell cache in background when network arrives.
 */
async function handleNavigationRequest(event, request, url) {
  let cacheUpdatePromise = null;

  const navUrl = new URL(request.url);
  navUrl.searchParams.set("_nav_cb", Date.now().toString());

  const networkPromise = (async () => {
    const response = await fetch(navUrl.toString(), {
      cache: "no-store",
      headers: {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
      },
    });
    if (response && response.ok) {
      const responseToCache = response.clone();
      cacheUpdatePromise = (async () => {
        try {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(request, responseToCache.clone());
          await cache.put("index.html", responseToCache.clone());
          await cache.put("./", responseToCache);
        } catch (e) {
          console.warn("Background cache update failed for navigation:", e);
        }
      })();
      event.waitUntil(cacheUpdatePromise);
    }
    return response;
  })();

  const timeoutPromise = new Promise((_, reject) =>
    setTimeout(() => reject(new Error("NAV_NETWORK_TIMEOUT_2500MS")), 2500)
  );

  try {
    const networkResponse = await Promise.race([networkPromise, timeoutPromise]);
    if (networkResponse && networkResponse.ok) {
      return networkResponse;
    }
    throw new Error("NAV_RESPONSE_NOT_OK");
  } catch (err) {
    // Timeout (> 2500ms) or network error: fall back to cached shell
    const cached =
      (await caches.match(request, { ignoreSearch: true })) ||
      (await caches.match("index.html", { ignoreSearch: true })) ||
      (await caches.match("./", { ignoreSearch: true }));

    if (cached) {
      return cached;
    }

    // If cache is empty, await network response
    return await networkPromise;
  }
}

/**
 * Default network-first handler for other static assets (icons, manifest, etc.)
 */
async function defaultNetworkFirst(request) {
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
    const res = await fetch(`data/live.json?_cb=${Date.now()}`, { cache: "no-store" });
    if (!res || !res.ok) return;
    const clone = res.clone();
    const cache = await caches.open(CACHE_NAME);
    await cache.put("data/live.json", clone.clone());
    await cache.put("/data/live.json", clone);
    const liveData = await res.json();
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    clients.forEach((client) => {
      client.postMessage({ type: "LIVE_RATE_HYDRATED", live: liveData, source: "background-sync" });
    });
  } catch (_) {}
}
