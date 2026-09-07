#!/usr/bin/env python3
"""
check_history_gaps.py

Read-only audit of data/history.json. Reports:
  - missing calendar days within the file's date range
  - out-of-range or missing rate_22k values
  - day-to-day jumps bigger than MAX_DAILY_CHANGE_PCT (matches the
    plausibility threshold update_gold.py uses for live data)
  - duplicate records for the same date+session with different rates

This script makes NO network calls and NEVER modifies history.json.
It only prints a report. Run it whenever you want to sanity-check the
file, or wire it into a workflow as a scheduled/manual check before
deciding whether backfill_history.py needs to run at all.

Usage:
    python3 check_history_gaps.py [path/to/history.json]

Exit code is 0 if no issues found, 1 if any issues were reported --
useful if you want a CI step to fail loudly on real gaps.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

MAX_DAILY_CHANGE_PCT = 8
MIN_VALID_RATE = 5000
MAX_VALID_RATE = 50000


def load_records(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = None
        for key in ("records", "history", "data"):
            if isinstance(data.get(key), list):
                records = data[key]
                break
        if records is None:
            raise ValueError(
                "history.json is a dict but has no records/history/data list"
            )
    else:
        raise ValueError("history.json is neither a list nor a dict")

    return [r for r in records if isinstance(r, dict)]


def find_missing_days(records):
    dates = sorted({r.get("date") for r in records if r.get("date")})
    if not dates:
        return [], None, None

    d0 = date.fromisoformat(dates[0])
    d1 = date.fromisoformat(dates[-1])

    present = set(dates)
    missing = []
    d = d0
    while d <= d1:
        if d.isoformat() not in present:
            missing.append(d.isoformat())
        d += timedelta(days=1)

    return missing, dates[0], dates[-1]


def find_bad_rates(records):
    bad = []
    for r in records:
        rate = r.get("rate_22k")
        if rate is None:
            bad.append((r.get("date"), r.get("time"), "missing rate_22k"))
            continue
        try:
            rate = int(rate)
        except (TypeError, ValueError):
            bad.append((r.get("date"), r.get("time"), f"non-numeric rate_22k: {rate!r}"))
            continue
        if not (MIN_VALID_RATE <= rate <= MAX_VALID_RATE):
            bad.append((r.get("date"), r.get("time"), f"out-of-range rate_22k: {rate}"))
    return bad


def find_big_jumps(records):
    """Compare each day's LAST record (closing rate) against the
    previous day's last record. Mirrors the daily-benchmark logic the
    frontend uses (dailyBenchmarks() in index.html), so this reports
    the same jumps a user would actually see on the chart.
    """
    daily = {}
    for r in sorted(
        records,
        key=lambda r: (str(r.get("date") or ""), str(r.get("time") or "")),
    ):
        d = r.get("date")
        rate = r.get("rate_22k")
        if d and rate is not None:
            try:
                daily[d] = int(rate)
            except (TypeError, ValueError):
                continue

    days = sorted(daily.keys())
    jumps = []
    for i in range(1, len(days)):
        prev_day, cur_day = days[i - 1], days[i]
        prev_rate, cur_rate = daily[prev_day], daily[cur_day]
        if prev_rate:
            pct = abs(cur_rate - prev_rate) / prev_rate * 100
            if pct > MAX_DAILY_CHANGE_PCT:
                jumps.append((prev_day, prev_rate, cur_day, cur_rate, round(pct, 1)))
    return jumps


def find_conflicting_duplicates(records):
    """Flag only genuinely suspicious same-date/session disagreement:
    two records sharing the SAME timestamp (or very same date+time)
    but reporting different rates. That can only happen from a bad
    write/merge, never from a normal intraday price move -- ordinary
    ticks through the day are expected to differ and are NOT a
    conflict (multiple ticks per day, each with a different rate, is
    completely normal; see 2026-09-02 in this project's own history
    for a legitimate example: 14175 -> 13935 -> 13942 across the day).
    """
    by_timestamp = {}
    for r in records:
        ts = r.get("timestamp") or (
            f"{r.get('date')}T{r.get('time')}" if r.get("date") and r.get("time") else None
        )
        rate = r.get("rate_22k")
        if not ts or rate is None:
            continue
        try:
            rate = int(rate)
        except (TypeError, ValueError):
            continue
        by_timestamp.setdefault(ts, set()).add(rate)

    conflicts = []
    for ts, rates in by_timestamp.items():
        if len(rates) > 1:
            conflicts.append((ts, sorted(rates)))
    return conflicts


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/history.json"

    if not Path(path).exists():
        print(f"ERROR: {path} not found")
        sys.exit(2)

    records = load_records(path)
    print(f"Loaded {len(records)} records from {path}")

    missing, first_date, last_date = find_missing_days(records)
    bad_rates = find_bad_rates(records)
    jumps = find_big_jumps(records)
    conflicts = find_conflicting_duplicates(records)

    issues_found = bool(missing or bad_rates or jumps or conflicts)

    print()
    print(f"Date range: {first_date} to {last_date}")
    print(f"Missing calendar days: {len(missing)}")
    if missing:
        # Group consecutive missing days into ranges for readability.
        ranges = []
        start = prev = missing[0]
        for d in missing[1:]:
            if date.fromisoformat(d) - date.fromisoformat(prev) == timedelta(days=1):
                prev = d
                continue
            ranges.append((start, prev))
            start = prev = d
        ranges.append((start, prev))

        for start, end in ranges:
            if start == end:
                print(f"  - {start}")
            else:
                print(f"  - {start} to {end}")

    print()
    print(f"Invalid/missing rate_22k records: {len(bad_rates)}")
    for d, t, reason in bad_rates[:20]:
        print(f"  - {d} {t}: {reason}")
    if len(bad_rates) > 20:
        print(f"  ... and {len(bad_rates) - 20} more")

    print()
    print(f"Day-to-day jumps > {MAX_DAILY_CHANGE_PCT}%: {len(jumps)}")
    for prev_day, prev_rate, cur_day, cur_rate, pct in jumps:
        print(f"  - {prev_day} ({prev_rate}) -> {cur_day} ({cur_rate}): {pct}%")

    print()
    print(f"Records with the same timestamp but different rates: {len(conflicts)}")
    for ts, rates in conflicts:
        print(f"  - {ts}: {rates}")

    print()
    if issues_found:
        print("RESULT: issues found -- see above.")
        sys.exit(1)
    else:
        print("RESULT: no issues found. history.json looks clean.")
        sys.exit(0)


if __name__ == "__main__":
    main()
