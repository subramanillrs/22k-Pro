# Chennai 22K Gold Rate Tracker & Valuation Suite

A fast, privacy-focused Progressive Web App (PWA) that tracks official **22K and 24K gold rates in Chennai** using daily Madras Jewellers & Diamond Merchants Association (MJDMA) benchmarks.

🌐 **Live App**: [https://subramanillrs.github.io/Chennai-22k-gold/](https://subramanillrs.github.io/Chennai-22k-gold/)

---

## Features

- **Live Chennai MJDMA Benchmark**: Real-time tracking of official Chennai 22K per-gram and 8g (one sovereign) prices.
- **Intraday Session Fixes**: Tracks Morning (AM) and Evening (PM) market fix updates with precise timestamps.
- **Interactive Price Chart**: Monotone cubic spline curve with scrub crosshairs, baseline comparisons, and multi-range filters (7D, 30D, 90D, 1Y, ALL).
- **Jewellery & Investment Calculator**: Breakdown of net weight, making charges (percentage or per-gram flat fee), GST (3%), exchange old gold valuation, and receipt slip.
- **Portfolio & ROI Tracker**: Track purchase lots, cost basis, unrealized gain/loss, and annualized returns (CAGR).
- **Price Target Alerts**: Set custom threshold alerts stored locally in browser storage.
- **Offline & PWA Ready**: Installable to home screen on iOS/Android, network-first caching via Service Worker (`sw.js`).
- **Data Export**: Complete historical dataset exportable as CSV.

---

## Architecture & Data Pipeline

```
GitHub Actions (Every 5 mins during trading windows + hourly heartbeat)
   │
   ├─► Scrapes LiveChennai (MJDMA official Chennai benchmark - Primary)
   ├─► Scrapes GoodReturns (Cross-verification & fallback - Secondary)
   │
   ▼
update_gold.py
   │
   ├─► Adaptive tolerance check (±1.5% or min ₹200 buffer)
   ├─► Plausibility check (guards against > 8% abnormal jumps)
   │
   ▼
Data Storage (Committed directly to repo)
   ├─► data/live.json            (Current price, spread, verification status)
   ├─► data/history.json         (Intraday and daily benchmarks since 2023)
   ├─► data/health_status.json   (Feed status: ok, stale, degraded, offline)
   ├─► data/summary.json         (All-time high/low, monthly & yearly averages)
   └─► data/monitoring_windows.json
   │
   ▼
GitHub Pages (Static Hosting)
   │
   ▼
User Browser / PWA (Loads same-origin data/*.json with offline fallback)
```

---

## Auditing & Verification

To audit the historical dataset for missing calendar days, out-of-range rates, or abnormal jumps:

```bash
python3 check_history_gaps.py data/history.json
```

---

## License

MIT

