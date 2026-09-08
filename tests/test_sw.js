// Test harness for sw.js in JavaScriptCore
class URL {
  constructor(url, base) {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      const match = url.match(/^(https?:\/\/[^\/?#]+)([^?#]*)(\?[^#]*)?(#.*)?$/);
      this.origin = match ? match[1] : "";
      this.pathname = match ? match[2] : "";
      this.search = match ? match[3] || "" : "";
      this.hash = match ? match[4] || "" : "";
    } else {
      this.origin = base ? new URL(base).origin : "";
      this.pathname = url.split("?")[0];
      this.search = url.includes("?") ? "?" + url.split("?")[1] : "";
    }
    const params = new Map();
    if (this.search && this.search.length > 1) {
      this.search.slice(1).split("&").forEach(pair => {
        const [k, v] = pair.split("=");
        params.set(k, v || "");
      });
    }
    this.searchParams = {
      set: (k, v) => params.set(k, v),
      get: (k) => params.get(k),
      has: (k) => params.has(k),
      toString: () => Array.from(params.entries()).map(([k, v]) => `${k}=${v}`).join("&")
    };
  }
  toString() {
    const qs = this.searchParams.toString();
    return `${this.origin}${this.pathname}${qs ? "?" + qs : ""}`;
  }
}

const listeners = {};
const self = {
  location: { origin: "https://gold.chennai" },
  addEventListener: (name, cb) => {
    listeners[name] = cb;
  },
  skipWaiting: () => {
    self._skipWaitingCalled = true;
  },
  clients: {
    claim: async () => {
      self._clientsClaimCalled = true;
    },
    matchAll: async () => [],
    openWindow: async () => {}
  }
};

const mockCache = new Map();
const caches = {
  open: async (name) => ({
    addAll: async (files) => {
      files.forEach(f => mockCache.set(f, "content of " + f));
    },
    add: async (file) => {
      mockCache.set(file, "content of " + file);
    },
    put: async (key, val) => {
      const k = (typeof key === "string") ? key : key.url;
      mockCache.set(k, val);
    }
  }),
  keys: async () => ["gold22k-shell-v5", "gold22k-shell-v6"],
  delete: async (name) => {
    mockCache.delete(name);
    return true;
  },
  match: async (key, opts) => {
    const k = (typeof key === "string") ? key : (key.url ? new URL(key.url).pathname : "");
    for (const [ck, val] of mockCache.entries()) {
      if (ck === k || ck.endsWith(k) || (k && k.endsWith(ck))) return val;
    }
    return null;
  }
};

// Mock Response and Request
function MockResponse(body, init = {}) {
  this.body = body;
  this.ok = init.status ? init.status >= 200 && init.status < 300 : true;
  this.status = init.status || 200;
  this.clone = () => new MockResponse(this.body, init);
  this.json = async () => JSON.parse(this.body);
}

function MockRequest(url, init = {}) {
  this.url = url;
  this.method = init.method || "GET";
  this.mode = init.mode || "cors";
  this.headers = init.headers || {};
}

let fetchCalls = [];
let fetchDelay = 10;
let fetchShouldFail = false;

const fetch = async (reqOrUrl, options = {}) => {
  const url = typeof reqOrUrl === "string" ? reqOrUrl : reqOrUrl.url;
  fetchCalls.push({ url, options });
  if (fetchDelay > 0) {
    await new Promise(r => setTimeout(r, fetchDelay));
  }
  if (fetchShouldFail) {
    throw new Error("Network simulated failure");
  }
  return new MockResponse('{"test": true}', { status: 200 });
};

// Now load and evaluate sw.js
print("Evaluating sw.js...");
load("sw.js");

// Assertions
function assert(cond, msg) {
  if (!cond) {
    throw new Error("ASSERTION FAILED: " + msg);
  }
  print("  ✓ " + msg);
}

async function runTests() {
  print("[TEST 1] CACHE_NAME and Lifecycle registration");
  assert(CACHE_NAME === "gold22k-shell-v6", "CACHE_NAME is gold22k-shell-v6");

  // Trigger install
  const installEvent = { waitUntil: (p) => p };
  listeners["install"](installEvent);
  assert(self._skipWaitingCalled === true, "self.skipWaiting() called immediately on install");

  // Trigger activate
  const activateEvent = { waitUntil: (p) => p };
  listeners["activate"](activateEvent);
  assert(self._clientsClaimCalled === true, "self.clients.claim() called immediately on activate");

  print("[TEST 2] Data Request Caching & Cache-busting");
  const dataReq = new MockRequest("https://gold.chennai/data/live.json");
  let respondWithPromise = null;
  const fetchEvent = {
    request: dataReq,
    respondWith: (p) => { respondWithPromise = p; },
    waitUntil: (p) => p
  };

  fetchCalls = [];
  listeners["fetch"](fetchEvent);
  const resp = await respondWithPromise;
  assert(resp && resp.ok, "Data request responded ok");
  assert(fetchCalls.length > 0, "Fetch was called for data");
  const dataFetch = fetchCalls[0];
  assert(dataFetch.url.includes("_cb="), "Fetch URL has _cb= cache buster: " + dataFetch.url);
  assert(dataFetch.options.cache === "no-store", "Fetch options include cache: 'no-store'");

  print("[TEST 3] Navigation Request Fast Network-first");
  const navReq = new MockRequest("https://gold.chennai/", { mode: "navigate" });
  let navRespondPromise = null;
  const navEvent = {
    request: navReq,
    respondWith: (p) => { navRespondPromise = p; },
    waitUntil: (p) => p
  };
  fetchCalls = [];
  listeners["fetch"](navEvent);
  const navResp = await navRespondPromise;
  assert(navResp && navResp.ok, "Navigation responded ok");
  assert(fetchCalls.length > 0, "Fetch was called for navigation");

  print("[TEST 4] Data Request Offline Fallback to Cache");
  // Clear mockCache to seed test specific entry
  mockCache.clear();
  mockCache.set("/data/live.json", new MockResponse('{"offline_rate": 14270}', { status: 200 }));
  mockCache.set("https://gold.chennai/data/live.json", new MockResponse('{"offline_rate": 14270}', { status: 200 }));
  fetchShouldFail = true;
  let offlineRespondPromise = null;
  const offlineEvent = {
    request: new MockRequest("https://gold.chennai/data/live.json"),
    respondWith: (p) => { offlineRespondPromise = p; },
    waitUntil: (p) => p
  };
  listeners["fetch"](offlineEvent);
  const offlineResp = await offlineRespondPromise;
  assert(offlineResp && offlineResp.ok, "Data request fell back to cache when offline");
  const offlineData = await offlineResp.json();
  assert(offlineData.offline_rate === 14270, "Cached offline data matches");
  fetchShouldFail = false;

  print("[TEST 5] Navigation Offline Fallback to Cached Shell");
  mockCache.set("index.html", new MockResponse("<html>Cached Shell</html>", { status: 200 }));
  fetchShouldFail = true;
  let navOfflinePromise = null;
  const navOfflineEvent = {
    request: new MockRequest("https://gold.chennai/index.html", { mode: "navigate" }),
    respondWith: (p) => { navOfflinePromise = p; },
    waitUntil: (p) => p
  };
  listeners["fetch"](navOfflineEvent);
  const navOfflineResp = await navOfflinePromise;
  assert(navOfflineResp && navOfflineResp.ok, "Navigation fell back to cached shell when offline");
  fetchShouldFail = false;

  print("[TEST 6] Data Request Timeout Fallback to Cache (> 2500ms)");
  mockCache.clear();
  mockCache.set("https://gold.chennai/data/live.json", new MockResponse('{"timeout_cached": true}', { status: 200 }));
  fetchDelay = 2700;
  const t0 = Date.now();
  let timeoutRespondPromise = null;
  const timeoutEvent = {
    request: new MockRequest("https://gold.chennai/data/live.json"),
    respondWith: (p) => { timeoutRespondPromise = p; },
    waitUntil: (p) => p
  };
  listeners["fetch"](timeoutEvent);
  const timeoutResp = await timeoutRespondPromise;
  const elapsed = Date.now() - t0;
  assert(timeoutResp && timeoutResp.ok, "Data request fell back to cache on timeout");
  const timeoutData = await timeoutResp.json();
  assert(timeoutData.timeout_cached === true, "Cached data served on timeout");
  assert(elapsed >= 2400 && elapsed < 2700, "Timeout triggered around 2500ms: " + elapsed + "ms");
  fetchDelay = 0;

  print("\nALL SW.JS VERIFICATION TESTS PASSED SUCCESSFULLY! ✓\n");
}

runTests().catch(err => {
  print("ERROR: " + err + "\n" + err.stack);
  quit(1);
});
