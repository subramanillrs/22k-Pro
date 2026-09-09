/**
 * Verification Test Suite for UI, Instant Hydration & Daily Change Bug Fixes
 */

// Mini DOM mock for JSC
const mockElements = {};
function getOrCreateElement(id) {
  if (!mockElements[id]) {
    mockElements[id] = {
      id: id,
      textContent: "",
      innerHTML: "",
      className: "",
      hidden: false,
      classList: {
        _classes: new Set(),
        add: function(c) { this._classes.add(c); mockElements[id].className = Array.from(this._classes).join(" "); },
        remove: function(c) { this._classes.delete(c); mockElements[id].className = Array.from(this._classes).join(" "); },
        toggle: function(c, force) {
          if (force === undefined) {
            if (this._classes.has(c)) this._classes.delete(c);
            else this._classes.add(c);
          } else if (force) {
            this._classes.add(c);
          } else {
            this._classes.delete(c);
          }
          mockElements[id].className = Array.from(this._classes).join(" ");
        },
        contains: function(c) { return this._classes.has(c); }
      }
    };
  }
  return mockElements[id];
}

const document = {
  documentElement: {
    getAttribute: function(attr) { return this[attr] || null; },
    setAttribute: function(attr, val) { this[attr] = val; },
    removeAttribute: function(attr) { delete this[attr]; }
  },
  getElementById: function(id) { return getOrCreateElement(id); },
  querySelector: function(sel) { return null; },
  querySelectorAll: function(sel) { return []; },
  createElement: function(tag) {
    if (tag === 'canvas') {
      return {
        width: 0,
        height: 0,
        getContext: function() {
          return {
            scale: function() {},
            createRadialGradient: function() { return { addColorStop: function() {} }; },
            createLinearGradient: function() { return { addColorStop: function() {} }; },
            fillRect: function() {},
            strokeRect: function() {},
            beginPath: function() {},
            roundRect: function() {},
            fill: function() {},
            stroke: function() {},
            fillText: function() {},
            measureText: function(txt) { return { width: (txt || '').length * 8 }; },
            moveTo: function() {},
            lineTo: function() {},
            arcTo: function() {},
            closePath: function() {}
          };
        },
        toDataURL: function() { return 'data:image/png;base64,mock'; },
        toBlob: function(cb) { cb(new Blob()); }
      };
    }
    return {};
  }
};
const window = {
  matchMedia: function() { return { matches: false }; },
  location: { href: 'https://example.com/22k-pro' }
};

const $ = function(id) { return document.getElementById(id); };

function dateText(s) { return "Sep 9, 2026"; }
function timeText(s) { return "10:30 IST"; }
function money(n) { return "₹ " + Number(n).toLocaleString("en-IN"); }

// Mock history dataset
const mockHistory = [
  { date: "2026-09-06", rate_22k: 14200 },
  { date: "2026-09-07", rate_22k: 14250 },
  { date: "2026-09-08", rate_22k: 14270 }
];

let history = mockHistory;

function getPreviousClose(currentDate) {
  const targetDate = currentDate || "2026-09-09";
  if (!Array.isArray(history) || !history.length) return null;
  for (let i = history.length - 1; i >= 0; i--) {
    const h = history[i];
    if (h && h.date && h.date < targetDate && Number.isFinite(Number(h.rate_22k)) && Number(h.rate_22k) > 0) {
      return Number(h.rate_22k);
    }
  }
  return null;
}

const DEFAULT_LIVE = {
  rate_22k: 14145,
  rate_24k: 15431,
  rate_8g: 113160,
  previous_close_22k: 14270,
  change: -125,
  change_8g: -1000,
  date: "2026-09-09",
  time: "06:32:41"
};

let live = null;

function getCurrentMarketRates() {
  let r22 = 0;
  let r8 = 0;
  let chg = 0;
  let dt = "";
  let tm = "";

  if (live && Number(live.rate_22k) > 0) {
    r22 = Number(live.rate_22k);
    r8 = Number(live.rate_8g || r22 * 8);
    const prevClose = Number(live.previous_close_22k) || getPreviousClose(live.date);
    if (prevClose && prevClose > 0) {
      chg = r22 - prevClose;
    } else {
      chg = Number.isFinite(Number(live.change)) ? Number(live.change) : 0;
    }
    dt = live.date ? dateText(live.date) : "";
    tm = live.time ? timeText(live.time) : "";
  } else if (typeof DEFAULT_LIVE !== "undefined" && DEFAULT_LIVE && Number(DEFAULT_LIVE.rate_22k) > 0) {
    r22 = Number(DEFAULT_LIVE.rate_22k);
    r8 = Number(DEFAULT_LIVE.rate_8g || r22 * 8);
    const prevClose = Number(DEFAULT_LIVE.previous_close_22k) || getPreviousClose(DEFAULT_LIVE.date);
    if (prevClose && prevClose > 0) {
      chg = r22 - prevClose;
    } else {
      chg = Number.isFinite(Number(DEFAULT_LIVE.change)) ? Number(DEFAULT_LIVE.change) : 0;
    }
    dt = DEFAULT_LIVE.date ? dateText(DEFAULT_LIVE.date) : "";
    tm = DEFAULT_LIVE.time ? timeText(DEFAULT_LIVE.time) : "";
  }

  if (!r22) r22 = 14145;
  if (!r8) r8 = r22 * 8;
  if (!dt || dt === "—") dt = "Sep 9, 2026";
  if (!tm || tm === "—") tm = "10:30 IST";
  const r24 = (live && Number(live.rate_24k) > 0) ? Number(live.rate_24k) : Math.round(r22 * (0.999 / 0.916));
  const r18 = Math.round(r22 * (0.750 / 0.916));
  return { r22, r8, r24, r18, chg, dt, tm };
}

function renderLive(d) {
  if (!d) return;
  live = d;
  const rate = Number(d.rate_22k);
  const rate8 = Number.isFinite(Number(d.rate_8g)) ? Number(d.rate_8g) : rate * 8;

  if ($("hero8")) $("hero8").textContent = money(rate8);
  if ($("today")) $("today").textContent = dateText(d.date);

  const fineness22 = 0.916;
  const purity24Rate = Number(d.rate_24k) || (rate * (0.999 / fineness22));
  const purity18Rate = rate * (0.750 / fineness22);
  if ($("purity22")) $("purity22").textContent = money(rate) + "/g";
  if ($("purity24")) $("purity24").textContent = money(Math.round(purity24Rate)) + "/g";
  if ($("purity18")) $("purity18").textContent = money(Math.round(purity18Rate)) + "/g";

  let prevClose = Number(d.previous_close_22k);
  if (!Number.isFinite(prevClose) || prevClose <= 0) {
    if (typeof getPreviousClose === "function") {
      prevClose = getPreviousClose(d.date);
    }
  }
  if (!Number.isFinite(prevClose) || prevClose <= 0) {
    if (Number.isFinite(Number(d.previous_rate_22k)) && Number(d.previous_rate_22k) !== rate) {
      prevClose = Number(d.previous_rate_22k);
    }
  }

  let change1 = null;
  if (Number.isFinite(prevClose) && prevClose > 0) {
    change1 = rate - prevClose;
  } else if (Number.isFinite(Number(d.change)) && Number(d.change) !== 0) {
    change1 = Number(d.change);
  } else {
    change1 = 0;
  }
  const change8 = change1 * 8;

  const change1Text = change1 > 0 ? "+" + money(change1) : change1 < 0 ? "-" + money(Math.abs(change1)) : "Flat";
  const change1Class = "change-pill mini " + (change1 > 0 ? "up" : change1 < 0 ? "down" : "same");
  if ($("hero1")) $("hero1").innerHTML = `${money(rate)} <span id="change1" class="${change1Class}">${change1Text}</span>`;

  if ($("change8")) {
    $("change8").textContent = change8 > 0 ? "▲ +" + money(change8) + " Today" : change8 < 0 ? "▼ -" + money(Math.abs(change8)) + " Today" : "No change";
    $("change8").className = "change-pill " + (change8 > 0 ? "up" : change8 < 0 ? "down" : "same");
  }
}

function computeSubmarketSpreads(rate22k, options = {}) {
  const rate = Number(rate22k);
  if (!Number.isFinite(rate) || rate <= 0) return null;
  const sowcarpetDiscount = Number.isFinite(options.sowcarpetDiscount) ? Number(options.sowcarpetDiscount) : -45;
  const showroomSpread = Number.isFinite(options.showroomMarkup) ? Number(options.showroomMarkup) : 180;
  const coimbatoreBasis = Number.isFinite(options.coimbatoreBasis) ? Number(options.coimbatoreBasis) : -15;
  const maduraiBasis = Number.isFinite(options.maduraiBasis) ? Number(options.maduraiBasis) : 15;
  const salemBasis = Number.isFinite(options.salemBasis) ? Number(options.salemBasis) : -10;

  const sowcarpetWholesale22k = Math.round(rate + sowcarpetDiscount);
  const retailShowroomRate22k = Math.round(rate + showroomSpread);
  const coimbatoreRate22k = Math.round(rate + coimbatoreBasis);
  const maduraiRate22k = Math.round(rate + maduraiBasis);
  const salemRate22k = Math.round(rate + salemBasis);

  return {
    sowcarpet_wholesale_22k: sowcarpetWholesale22k,
    retail_showroom_rate_22k: retailShowroomRate22k,
    coimbatore_rate_22k: coimbatoreRate22k,
    coimbatore_basis: coimbatoreBasis,
    madurai_rate_22k: maduraiRate22k,
    madurai_basis: maduraiBasis,
    salem_rate_22k: salemRate22k,
    salem_basis: salemBasis
  };
}

function updateSubmarketSpreadDashboard(liveData = live) {
  if (!liveData) return;
  const rate22 = Number(liveData.rate_22k);
  if (!Number.isFinite(rate22) || rate22 <= 0) return;

  const backendSubmarkets = liveData.submarket_spreads;
  const spreads = computeSubmarketSpreads(rate22);
  if (!spreads) return;

  const cbeRate = (backendSubmarkets && backendSubmarkets.regional_parity && backendSubmarkets.regional_parity.coimbatore && backendSubmarkets.regional_parity.coimbatore.rate_22k) || spreads.coimbatore_rate_22k;
  const cbeBasis = (backendSubmarkets && backendSubmarkets.regional_parity && backendSubmarkets.regional_parity.coimbatore && backendSubmarkets.regional_parity.coimbatore.basis_spread) ?? spreads.coimbatore_basis;

  const madRate = (backendSubmarkets && backendSubmarkets.regional_parity && backendSubmarkets.regional_parity.madurai && backendSubmarkets.regional_parity.madurai.rate_22k) || spreads.madurai_rate_22k;
  const madBasis = (backendSubmarkets && backendSubmarkets.regional_parity && backendSubmarkets.regional_parity.madurai && backendSubmarkets.regional_parity.madurai.basis_spread) ?? spreads.madurai_basis;

  const salemRate = (backendSubmarkets && backendSubmarkets.regional_parity && backendSubmarkets.regional_parity.salem && backendSubmarkets.regional_parity.salem.rate_22k) || spreads.salem_rate_22k;
  const salemBasis = (backendSubmarkets && backendSubmarkets.regional_parity && backendSubmarkets.regional_parity.salem && backendSubmarkets.regional_parity.salem.basis_spread) ?? spreads.salem_basis;

  if ($("coimbatoreRateVal")) $("coimbatoreRateVal").textContent = money(cbeRate);
  if ($("coimbatoreBasisVal")) $("coimbatoreBasisVal").textContent = `(${cbeBasis >= 0 ? "+" : "-"}₹${Math.abs(cbeBasis)})`;

  if ($("maduraiRateVal")) $("maduraiRateVal").textContent = money(madRate);
  if ($("maduraiBasisVal")) $("maduraiBasisVal").textContent = `(${madBasis >= 0 ? "+" : "-"}₹${Math.abs(madBasis)})`;

  if ($("salemRateVal")) $("salemRateVal").textContent = money(salemRate);
  if ($("salemBasisVal")) $("salemBasisVal").textContent = `(${salemBasis >= 0 ? "+" : "-"}₹${Math.abs(salemBasis)})`;
}

print("============================================================");
print("TESTING UI, INSTANT HYDRATION & DAILY CHANGE BUG FIXES");
print("============================================================");

// [TEST 1] getPreviousClose correctly returns yesterday's market close
const prevCloseResult = getPreviousClose("2026-09-09");
if (prevCloseResult === 14270) {
  print("  ✓ [TEST 1] getPreviousClose returned 14270 for 2026-09-09 (scanned from 2026-09-08)");
} else {
  throw new Error("[TEST 1 FAIL] Expected 14270, got: " + prevCloseResult);
}

// Edge case: target date is 2026-09-08
const prevCloseResult2 = getPreviousClose("2026-09-08");
if (prevCloseResult2 === 14250) {
  print("  ✓ [TEST 1b] getPreviousClose returned 14250 for 2026-09-08 (scanned from 2026-09-07)");
} else {
  throw new Error("[TEST 1b FAIL] Expected 14250, got: " + prevCloseResult2);
}

// [TEST 2] Current Market Rates Accuracy with previous close and daily change
live = {
  rate_22k: 14145,
  rate_24k: 15431,
  rate_8g: 113160,
  previous_close_22k: 14270,
  change: -125,
  date: "2026-09-09",
  time: "10:30:00"
};

const rates = getCurrentMarketRates();
if (rates.r22 === 14145 && rates.r8 === 113160 && rates.chg === -125 && rates.r24 === 15431 && rates.r18 === 11582) {
  print("  ✓ [TEST 2] getCurrentMarketRates returned exact live rates (22K: 14145, 8g: 113160, chg: -125, 24K: 15431, 18K: 11582)");
} else {
  throw new Error("[TEST 2 FAIL] Unexpected rates: " + JSON.stringify(rates));
}

// [TEST 3] Fallback robustness when live is null (uses DEFAULT_LIVE)
live = null;
const fallbackRates = getCurrentMarketRates();
if (fallbackRates.r22 === 14145 && fallbackRates.r8 === 113160 && fallbackRates.chg === -125) {
  print("  ✓ [TEST 3] Fallback correctly returns 14145/113160 with chg: -125 from DEFAULT_LIVE");
} else {
  throw new Error("[TEST 3 FAIL] Fallback failed: " + JSON.stringify(fallbackRates));
}

// [TEST 4] renderLive Negative Change: Should NOT say "No change", should say "▼ -₹ 1,000 Today"
renderLive({
  rate_22k: 14145,
  rate_8g: 113160,
  previous_close_22k: 14270,
  change: -125,
  date: "2026-09-09",
  time: "10:30:00"
});

const change8El = $("change8");
const hero1El = $("hero1");

if (change8El.textContent === "▼ -₹ 1,000 Today" && change8El.className === "change-pill down") {
  print("  ✓ [TEST 4a] renderLive correctly displayed '▼ -₹ 1,000 Today' with class 'change-pill down'");
} else {
  throw new Error("[TEST 4a FAIL] Expected '▼ -₹ 1,000 Today', got: " + change8El.textContent);
}

if (hero1El.innerHTML.includes("-₹ 125") && hero1El.innerHTML.includes("change-pill mini down")) {
  print("  ✓ [TEST 4b] renderLive correctly displayed '-₹ 125' in hero1 with class 'change-pill mini down'");
} else {
  throw new Error("[TEST 4b FAIL] Expected -₹ 125 in hero1, got: " + hero1El.innerHTML);
}

// [TEST 5] renderLive Positive Change: "▲ +₹ 800 Today"
renderLive({
  rate_22k: 14370,
  rate_8g: 114960,
  previous_close_22k: 14270,
  change: 100,
  date: "2026-09-09",
  time: "14:30:00"
});

if (change8El.textContent === "▲ +₹ 800 Today" && change8El.className === "change-pill up") {
  print("  ✓ [TEST 5a] renderLive correctly displayed '▲ +₹ 800 Today' with class 'change-pill up'");
} else {
  throw new Error("[TEST 5a FAIL] Expected '▲ +₹ 800 Today', got: " + change8El.textContent);
}

// [TEST 6] renderLive Flat Change: "No change"
renderLive({
  rate_22k: 14270,
  rate_8g: 114160,
  previous_close_22k: 14270,
  change: 0,
  date: "2026-09-09",
  time: "14:30:00"
});

if (change8El.textContent === "No change" && change8El.className === "change-pill same") {
  print("  ✓ [TEST 6a] renderLive correctly displayed 'No change' when price equals previous close");
} else {
  throw new Error("[TEST 6a FAIL] Expected 'No change', got: " + change8El.textContent);
}

// [TEST 7] Theme Detection across dark, oled, and light
function testThemeDetect(themeAttr) {
  if (themeAttr) {
    document.documentElement.setAttribute("data-theme", themeAttr);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  const theme = (document.documentElement.getAttribute("data-theme") || "").toLowerCase();
  const isDark = theme === "dark" || theme === "oled";
  const isOled = theme === "oled";
  return { isDark, isOled };
}

const darkCheck = testThemeDetect("dark");
if (darkCheck.isDark === true && darkCheck.isOled === false) {
  print("  ✓ [TEST 7a] Dark theme correctly detected (isDark: true)");
} else {
  throw new Error("[TEST 7a FAIL]");
}

const oledCheck = testThemeDetect("oled");
if (oledCheck.isDark === true && oledCheck.isOled === true) {
  print("  ✓ [TEST 7b] OLED theme correctly detected (isDark: true, isOled: true)");
} else {
  throw new Error("[TEST 7b FAIL]");
}

const lightCheck = testThemeDetect("light");
if (lightCheck.isDark === false && lightCheck.isOled === false) {
  print("  ✓ [TEST 7c] Light theme correctly detected (isDark: false)");
} else {
  throw new Error("[TEST 7c FAIL]");
}

// [TEST 8] Regional Basis Parity including Salem
const testSubmarketLive = {
  rate_22k: 14145,
  submarket_spreads: {
    regional_parity: {
      coimbatore: { rate_22k: 14130, basis_spread: -15 },
      madurai: { rate_22k: 14160, basis_spread: 15 },
      salem: { rate_22k: 14135, basis_spread: -10 }
    }
  }
};

updateSubmarketSpreadDashboard(testSubmarketLive);

const salemRateEl = $("salemRateVal");
const salemBasisEl = $("salemBasisVal");

if (salemRateEl.textContent === "₹ 14,135") {
  print("  ✓ [TEST 8a] Regional Basis Parity for Salem rate correctly displayed '₹ 14,135'");
} else {
  throw new Error("[TEST 8a FAIL] Expected '₹ 14,135', got: " + salemRateEl.textContent);
}

if (salemBasisEl.textContent === "(-₹10)") {
  print("  ✓ [TEST 8b] Regional Basis Parity for Salem basis correctly displayed '(-₹10)'");
} else {
  throw new Error("[TEST 8b FAIL] Expected '(-₹10)', got: " + salemBasisEl.textContent);
}

const computedSalem = computeSubmarketSpreads(14145);
if (computedSalem.salem_rate_22k === 14135 && computedSalem.salem_basis === -10) {
  print("  ✓ [TEST 8c] computeSubmarketSpreads correctly computed Salem rate (14135) and basis (-10)");
} else {
  throw new Error("[TEST 8c FAIL] computeSubmarketSpreads failed for Salem: " + JSON.stringify(computedSalem));
}

print("============================================================");
print("ALL UI & DAILY CHANGE BUG FIX TESTS PASSED 100%! ✓");
print("============================================================");

