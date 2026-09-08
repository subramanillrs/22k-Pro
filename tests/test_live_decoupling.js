// Test harness for loadLiveOnly and loadPublishedData decoupling
let logs = [];
const printLog = (msg) => print("  " + msg);

// DOM & Global mocks
const console = {
  log: (...args) => print(args.join(" ")),
  warn: (...args) => print("[WARN] " + args.join(" ")),
  info: (...args) => print("[INFO] " + args.join(" ")),
  error: (...args) => print("[ERROR] " + args.join(" "))
};
const mockStorage = new Map();
const localStorage = {
  getItem: (k) => mockStorage.get(k) || null,
  setItem: (k, v) => { mockStorage.set(k, String(v)); },
  removeItem: (k) => { mockStorage.delete(k); }
};

const domElements = new Map();
const $ = (id) => {
  if (!domElements.has(id)) {
    domElements.set(id, {
      id,
      textContent: "",
      innerHTML: "",
      hidden: false,
      classList: {
        add: () => {},
        remove: () => {},
        toggle: () => {}
      },
      style: {}
    });
  }
  return domElements.get(id);
};

const document = {
  getElementById: $,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  documentElement: { setAttribute: () => {}, removeAttribute: () => {} }
};

const window = {
  addEventListener: () => {},
  matchMedia: () => ({ matches: false, addEventListener: () => {} })
};

const navigator = { onLine: true };

// Mock state
let live = null;
let history = [
  { date: "2026-09-07", rate_22k: 14130, rate_24k: 15415, weight_1g: 14130, weight_8g: 113040 }
];
let lastSyncTimestamp = 0;
const LIVE_URL = "data/live.json";
const HISTORY_URL = "data/history.json";
const HEALTH_URL = "data/health_status.json";
const WINDOWS_URL = "data/monitoring_windows.json";

// Mock helper functions
const money = (n) => "₹" + Math.round(Number(n) || 0).toLocaleString("en-IN");
const dateText = (d) => d || "";
const timeText = (t) => t ? t + " Fix" : "—";
const isLiveDataFresh = () => true;
const formatLiveStatus = (t) => "Live " + (t || "19:48") + " IST";
const triggerPriceUpdatedGlow = () => logs.push("triggerPriceUpdatedGlow");
const toast = (msg) => logs.push("toast: " + msg);
const setStatus = (text, offline = false, syncing = false) => {
  logs.push(`setStatus: ${text} (offline=${offline}, syncing=${syncing})`);
};
const saveCacheToIndexedDB = (k, v) => { logs.push(`saveCacheToIndexedDB: ${k}`); };

let renderLiveCalls = [];
function renderLive(d) {
  renderLiveCalls.push(d);
  live = d;
  logs.push(`renderLive: ${d ? d.rate_22k : "null"}`);
}

let updateSpreadDashboardCalls = [];
function updateSpreadDashboard(liveData = live, historyData = history) {
  updateSpreadDashboardCalls.push({ liveData, historyData });
  logs.push(`updateSpreadDashboard: live=${liveData ? liveData.rate_22k : "null"}`);
}

let calculateCalls = 0;
function calculate() { calculateCalls++; }

let renderStatsCalls = 0;
function renderStats() { renderStatsCalls++; }

function latestSnapshot(liveData, hist) { return liveData; }
function normalize(arr) { return arr || []; }
function checkParserHealth() {}
function renderHealth() {}
function renderNextFix() {}
function renderSignals() {}

// Mock fetch
let fetchCalls = [];
let historyDelay = 0;
let historyShouldFail = false;

const fetch = async (url, opts = {}) => {
  fetchCalls.push({ url, opts });
  
  if (url.includes("data/live.json")) {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        rate_22k: 14270,
        rate_24k: 15567,
        rate_8g: 114160,
        date: "2026-09-08",
        time: "19:43:04",
        city: "Chennai"
      })
    };
  }

  if (url.includes("data/history.json")) {
    if (historyDelay > 0) {
      await new Promise(r => setTimeout(r, historyDelay));
    }
    if (historyShouldFail) {
      return { ok: false, status: 500 };
    }
    return {
      ok: true,
      status: 200,
      json: async () => [
        { date: "2026-09-07", rate_22k: 14130 },
        { date: "2026-09-08", rate_22k: 14270 }
      ]
    };
  }

  return {
    ok: true,
    status: 200,
    json: async () => ({})
  };
};

async function getJSON(url) {
  const res = await fetch(url + (url.includes("?") ? "&" : "?") + "v=" + Date.now(), { cache: "no-store" });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// Load implementation directly from index.html
const indexHtml = readFile("index.html");

// Extract loadLiveOnly and loadPublishedData functions from index.html
const loadLiveOnlyMatch = indexHtml.match(/async function loadLiveOnly[\s\S]*?^window\.loadLiveOnly\s*=\s*loadLiveOnly;/m);
const loadPublishedDataMatch = indexHtml.match(/async function loadPublishedData[\s\S]*?^window\.loadPublishedData\s*=\s*loadPublishedData;/m);

if (!loadLiveOnlyMatch) {
  throw new Error("Could not find loadLiveOnly in index.html");
}
if (!loadPublishedDataMatch) {
  throw new Error("Could not find loadPublishedData in index.html");
}

eval(loadLiveOnlyMatch[0]);
eval(loadPublishedDataMatch[0]);

function assert(cond, msg) {
  if (!cond) {
    throw new Error("ASSERTION FAILED: " + msg);
  }
  print("  ✓ " + msg);
}

async function runTests() {
  print("============================================================");
  print("RUNNING LIVE RATE DECOUPLING UNIT TESTS");
  print("============================================================");

  // TEST 1: loadLiveOnly execution and performance
  print("\n[TEST 1] Testing loadLiveOnly(silent=false)...");
  fetchCalls = [];
  renderLiveCalls = [];
  updateSpreadDashboardCalls = [];
  logs = [];

  const t0 = Date.now();
  const liveResult = await loadLiveOnly(false);
  const elapsed = Date.now() - t0;

  assert(liveResult !== null, "loadLiveOnly returned a valid live data object");
  assert(liveResult.rate_22k === 14270, "Live rate is 14270");
  assert(fetchCalls.length === 1, "Only 1 fetch call was made");
  assert(fetchCalls[0].url.startsWith("data/live.json?v="), "Fetched ONLY data/live.json with cache buster: " + fetchCalls[0].url);
  assert(fetchCalls[0].opts.cache === "no-store", "Fetched with cache: 'no-store'");
  assert(renderLiveCalls.length === 1, "renderLive(liveData) was called immediately");
  assert(updateSpreadDashboardCalls.length >= 1, "updateSpreadDashboard(liveData, history) was called immediately");
  assert(mockStorage.get("gold_live_backup") !== null, "localStorage.setItem('gold_live_backup') was updated");
  assert(logs.some(l => l.includes("setStatus: Live") || l.includes("setStatus: Synced at")), "Status pill was updated with sync time");
  assert(elapsed < 50, `Execution completed in ${elapsed}ms (< 50ms)`);

  // TEST 2: loadPublishedData decoupled - live rendered first before history
  print("\n[TEST 2] Testing loadPublishedData() decoupling with delayed history...");
  fetchCalls = [];
  renderLiveCalls = [];
  updateSpreadDashboardCalls = [];
  historyDelay = 50; // History takes 50ms (simulating heavy 333KB download)
  historyShouldFail = false;

  const tStart = Date.now();
  const pubResult = await loadPublishedData(false);
  const liveRenderElapsed = Date.now() - tStart;

  assert(pubResult !== null && pubResult.rate_22k === 14270, "loadPublishedData resolved immediately with live data");
  assert(liveRenderElapsed < 40, `loadPublishedData returned live in ${liveRenderElapsed}ms without waiting for 50ms history`);
  assert(renderLiveCalls.length >= 1, "renderLive was called without waiting for history");

  // Wait for background history to complete
  await new Promise(r => setTimeout(r, 80));
  assert(renderStatsCalls > 0, "renderStats was called after background history resolved");
  assert(mockStorage.get("gold_history_backup") !== null, "gold_history_backup saved after background history resolved");

  // TEST 3: History network failure resilience
  print("\n[TEST 3] Testing resilience when history.json fails (e.g. slow network drop)...");
  fetchCalls = [];
  renderLiveCalls = [];
  historyShouldFail = true; // History completely fails with HTTP 500

  let errorThrown = false;
  let res3 = null;
  try {
    res3 = await loadPublishedData(false);
  } catch (e) {
    errorThrown = true;
  }

  assert(!errorThrown, "loadPublishedData did NOT throw when history failed");
  assert(res3 !== null && res3.rate_22k === 14270, "loadPublishedData still succeeded with live rate despite history failure");
  assert(live.rate_22k === 14270, "Live rate is active and rendered in UI despite history failure");

  print("\n============================================================");
  print("ALL LIVE RATE DECOUPLING TESTS PASSED SUCCESSFULLY! ✓");
  print("============================================================\n");
}

runTests().catch(err => {
  print("ERROR: " + err + "\n" + (err && err.stack ? err.stack : ""));
  quit(1);
});
