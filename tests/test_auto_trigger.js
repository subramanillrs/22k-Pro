// Test suite for Agent 5: Edge Worker Auto-Heal & Stale Data Trigger Bridge
// Run with: /System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc tests/test_auto_trigger.js

// Mock environment
const mockStorage = new Map();
const localStorage = {
  getItem: (k) => mockStorage.has(k) ? mockStorage.get(k) : null,
  setItem: (k, v) => mockStorage.set(k, String(v)),
  removeItem: (k) => mockStorage.delete(k),
  clear: () => mockStorage.clear()
};

const window = {
  localStorage: localStorage
};

const WORKER_URL = "https://gold-price-fetch.subramanilrs.workers.dev/";
let fetchCalls = [];
async function fetch(url, options) {
  fetchCalls.push({ url, options });
  return {
    ok: true,
    status: 200,
    json: async () => ({ status: "ok" })
  };
}

let live = null;

// ============================================================
// AGENT 5 CODE TO TEST
// ============================================================
const WORKER_AUTO_TRIGGER_KEY = "last_worker_auto_trigger";
const WORKER_AUTO_TRIGGER_COOLDOWN_MS = 10 * 60 * 1000; // 10 minutes debounce
const WORKER_STALE_THRESHOLD_MS = 20 * 60 * 1000; // 20 minutes stale threshold

let workerAutoTriggerInProgress = false;

function isDuringActiveFixHours(nowDate = new Date()) {
  let minutes = -1;
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23"
    }).formatToParts(nowDate);
    const h = Number(parts.find(p => p.type === "hour")?.value);
    const m = Number(parts.find(p => p.type === "minute")?.value);
    if (Number.isFinite(h) && Number.isFinite(m)) {
      minutes = h * 60 + m;
    }
  } catch (_) {}

  if (minutes < 0) {
    const utcMinutes = nowDate.getUTCHours() * 60 + nowDate.getUTCMinutes();
    minutes = (utcMinutes + 330) % 1440;
  }

  const isMorningWindow = (minutes >= 570 && minutes <= 690);
  const isEveningWindow = (minutes >= 1020 && minutes <= 1200);

  return isMorningWindow || isEveningWindow;
}

function getLiveSnapshotTimestamp(liveData = live) {
  if (!liveData) return 0;
  if (typeof recordTimestamp === "function") {
    const t = recordTimestamp(liveData);
    if (t > 0) return t;
  }
  const fields = [liveData.timestamp, liveData.last_checked_at, liveData.updated_at, liveData.verified_at];
  for (const f of fields) {
    if (f) {
      const t = new Date(f).getTime();
      if (Number.isFinite(t) && t > 0) return t;
    }
  }
  if (liveData.date) {
    const t = new Date(`${liveData.date}T${liveData.time || "00:00:00"}+05:30`).getTime();
    if (Number.isFinite(t) && t > 0) return t;
  }
  return 0;
}

async function checkAndAutoTriggerWorker(targetLive, customNow) {
  const currentLive = targetLive || live || (() => {
    try {
      return JSON.parse(localStorage.getItem("gold_live_backup") || "null");
    } catch (_) { return null; }
  })();

  const now = customNow || Date.now();

  // 1. Verify we are in active fix hours (09:30 - 11:30 IST or 17:00 - 20:00 IST)
  if (!isDuringActiveFixHours(new Date(now))) {
    return false;
  }

  // 2. Check if live rate timestamp is older than 20 minutes (meaning no fix has landed yet)
  const rateTs = getLiveSnapshotTimestamp(currentLive);
  const isOlderThan20Min = !rateTs || ((now - rateTs) > WORKER_STALE_THRESHOLD_MS);
  if (!isOlderThan20Min) {
    return false;
  }

  // 3. Debounce/throttle: fire at most once every 10 minutes per device
  let lastTrigger = 0;
  try {
    const lastStr = localStorage.getItem(WORKER_AUTO_TRIGGER_KEY);
    if (lastStr) lastTrigger = Number(lastStr) || 0;
  } catch (_) {}

  if (Number.isFinite(lastTrigger) && (now - lastTrigger) < WORKER_AUTO_TRIGGER_COOLDOWN_MS) {
    return false;
  }

  if (workerAutoTriggerInProgress) {
    return false;
  }

  workerAutoTriggerInProgress = true;
  try {
    localStorage.setItem(WORKER_AUTO_TRIGGER_KEY, String(now));
  } catch (_) {}

  try {
    const fetchPromise = fetch(WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: true })
    });

    return true;
  } catch (err) {
    return false;
  } finally {
    workerAutoTriggerInProgress = false;
  }
}

// ============================================================
// TESTS
// ============================================================
function assert(cond, msg) {
  if (!cond) {
    print("FAIL: " + msg);
    throw new Error(msg);
  }
  print("  PASS: " + msg);
}

async function runTests() {
  print("============================================================");
  print("TESTING AGENT 5: EDGE WORKER AUTO-HEAL WATCHDOG");
  print("============================================================");

  function makeISTDate(hour, minute) {
    const pad = (n) => String(n).padStart(2, "0");
    return new Date("2026-09-08T" + pad(hour) + ":" + pad(minute) + ":00+05:30");
  }

  print("[TEST 1] Active Fix Hours Window Detection (IST)");
  assert(isDuringActiveFixHours(makeISTDate(9, 29)) === false, "09:29 IST is outside AM window");
  assert(isDuringActiveFixHours(makeISTDate(9, 30)) === true, "09:30 IST is inside AM window");
  assert(isDuringActiveFixHours(makeISTDate(10, 30)) === true, "10:30 IST is inside AM window");
  assert(isDuringActiveFixHours(makeISTDate(11, 30)) === true, "11:30 IST is inside AM window");
  assert(isDuringActiveFixHours(makeISTDate(11, 31)) === false, "11:31 IST is outside AM window");
  assert(isDuringActiveFixHours(makeISTDate(14, 0)) === false, "14:00 IST is outside fix windows");
  assert(isDuringActiveFixHours(makeISTDate(16, 59)) === false, "16:59 IST is outside PM window");
  assert(isDuringActiveFixHours(makeISTDate(17, 0)) === true, "17:00 IST is inside PM window");
  assert(isDuringActiveFixHours(makeISTDate(18, 30)) === true, "18:30 IST is inside PM window");
  assert(isDuringActiveFixHours(makeISTDate(20, 0)) === true, "20:00 IST is inside PM window");
  assert(isDuringActiveFixHours(makeISTDate(20, 1)) === false, "20:01 IST is outside PM window");

  print("[TEST 2] Live Snapshot Timestamp Extraction");
  const testLive1 = { timestamp: "2026-09-08T19:30:00+05:30" };
  assert(getLiveSnapshotTimestamp(testLive1) === new Date("2026-09-08T19:30:00+05:30").getTime(), "Extracts ISO timestamp");

  const testLive2 = { date: "2026-09-08", time: "10:15:00" };
  assert(getLiveSnapshotTimestamp(testLive2) === new Date("2026-09-08T10:15:00+05:30").getTime(), "Extracts date + time");

  const testLive3 = { last_checked_at: "2026-09-08T17:45:00+05:30" };
  assert(getLiveSnapshotTimestamp(testLive3) === new Date("2026-09-08T17:45:00+05:30").getTime(), "Extracts last_checked_at");

  print("[TEST 3] Auto-Heal Trigger Conditions");
  localStorage.clear();
  fetchCalls = [];

  // Case A: Outside fix hours -> should NOT trigger
  const middayDate = makeISTDate(14, 0).getTime();
  const oldLive = { timestamp: "2026-09-08T09:00:00+05:30" };
  const resMidday = await checkAndAutoTriggerWorker(oldLive, middayDate);
  assert(resMidday === false, "Does not trigger outside fix hours (14:00 IST)");
  assert(fetchCalls.length === 0, "No worker fetch called");

  // Case B: During fix hours, but fresh rate (<20 mins) -> should NOT trigger
  const eveningNow = makeISTDate(18, 0).getTime();
  const freshLive = { timestamp: new Date("2026-09-08T17:50:00+05:30").toISOString() }; // 10 mins old
  const resFresh = await checkAndAutoTriggerWorker(freshLive, eveningNow);
  assert(resFresh === false, "Does not trigger when rate is fresh (10 mins old)");
  assert(fetchCalls.length === 0, "No worker fetch called");

  // Case C: During fix hours, rate is older than 20 mins (e.g. 25 mins old) -> SHOULD trigger!
  const staleLive = { timestamp: new Date("2026-09-08T17:35:00+05:30").toISOString() }; // 25 mins old
  const resStale = await checkAndAutoTriggerWorker(staleLive, eveningNow);
  assert(resStale === true, "Triggers when rate is >20 mins old during active fix hours");
  assert(fetchCalls.length === 1, "Dispatched 1 worker fetch");
  assert(fetchCalls[0].url === WORKER_URL, "Target URL matches WORKER_URL");
  assert(fetchCalls[0].options.method === "POST", "Method is POST");
  const parsedBody = JSON.parse(fetchCalls[0].options.body);
  assert(parsedBody.force === true, "Body is { force: true }");
  assert(localStorage.getItem("last_worker_auto_trigger") === String(eveningNow), "Records last_worker_auto_trigger in localStorage");

  print("[TEST 4] 10-Minute Debounce / Throttle Protection");
  // Try triggering again 2 minutes later (18:02) -> should be throttled
  const twoMinsLater = eveningNow + 2 * 60 * 1000;
  const resThrottled = await checkAndAutoTriggerWorker(staleLive, twoMinsLater);
  assert(resThrottled === false, "Throttled: Does not fire within 10 minutes");
  assert(fetchCalls.length === 1, "Fetch count remains 1 (no extra call)");

  // Try triggering 9 minutes later (18:09) -> still throttled
  const nineMinsLater = eveningNow + 9 * 60 * 1000;
  const resStillThrottled = await checkAndAutoTriggerWorker(staleLive, nineMinsLater);
  assert(resStillThrottled === false, "Still throttled at 9 minutes");
  assert(fetchCalls.length === 1, "Fetch count remains 1");

  // Try triggering 11 minutes later (18:11) -> should fire!
  const elevenMinsLater = eveningNow + 11 * 60 * 1000;
  const resAllowed = await checkAndAutoTriggerWorker(staleLive, elevenMinsLater);
  assert(resAllowed === true, "Allows new trigger after 10 minute debounce window expires");
  assert(fetchCalls.length === 2, "Fetch count increased to 2");
  assert(localStorage.getItem("last_worker_auto_trigger") === String(elevenMinsLater), "Updates last_worker_auto_trigger timestamp");

  print("============================================================");
  print("ALL AGENT 5 WATCHDOG TESTS PASSED PERFECTLY!");
  print("============================================================");
}

runTests();
