#!/usr/bin/env python3
"""
backfill_history.py

Fill SPECIFIC missing days in data/history.json by re-scraping
LiveChennai's monthly gold-rate-history page. This is a targeted
backfill, not a full rebuild:

  1. Run check_history_gaps.py first to find which days are missing.
  2. This script re-scrapes only the calendar months that contain a
     missing day, extracts the daily rows from each month's history
     table, and merges in ONLY the records for the missing dates.
  3. Existing records are never touched, overwritten, or removed.
     save_json's atomic-write pattern (write to .tmp, then rename) is
     reused from update_gold.py so a crash mid-run can't corrupt the
     file.

STATUS: the network calls and HTML-table parsing in
fetch_month_history() are STUBBED. Every attempt to reach
livechennai.com from the sandbox that produced this script returned
either a 403 (direct requests) or an empty/unpopulated table (browser
fetch tool) -- the monthly history table did not render with a plain
GET request in either case, which suggests the real page needs a
session/referer a plain script doesn't have, or renders the table via
JS/AJAX rather than server-side HTML.

Before running this for real:
  1. Open https://www.livechennai.com/get_goldrate_history.asp in an
     actual browser, pick a month/year, and check whether the table
     populates. If it does, use the browser devtools Network tab to
     see the real request it fires (it may be a POST with form data,
     or a separate AJAX endpoint) -- that's what fetch_month_history()
     below needs to replicate.
  2. Once you can see real <tr> rows for a month, update
     fetch_month_history() to match that markup. The function already
     has the merge/dedup/save logic built around it, so that should be
     the only piece to fill in.
  3. Test with --dry-run first (see below) to see what WOULD be added
     without writing anything.

Usage:
    python3 backfill_history.py --dry-run          # show what's missing, fetch nothing
    python3 backfill_history.py                    # actually fetch and merge missing days
    python3 backfill_history.py --history path/to/history.json
"""

import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

MIN_VALID_RATE = 5000
MAX_VALID_RATE = 50000
REQUEST_TIMEOUT = 20
REQUEST_DELAY_SECONDS = 2  # be polite between month requests

LIVECHENNAI_HISTORY_URL = "https://www.livechennai.com/get_goldrate_history.asp"

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/18.0 Safari/605.1.15"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-IN,en;q=0.9",
    }
)


# ============================================================
# SHARED HELPERS (mirrors update_gold.py so records this script
# writes are byte-for-byte in the same shape as the normal pipeline)
# ============================================================

def valid_gold_rate(value):
    if value is None:
        return False
    try:
        val = int(value)
        return MIN_VALID_RATE <= val <= MAX_VALID_RATE
    except (ValueError, TypeError):
        return False


def load_json(path, default):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"WARNING: could not read {path}: {exc}")
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp.replace(path)


def extract_history_records(data):
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("records", "history", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


# ============================================================
# GAP DETECTION (same logic as check_history_gaps.py, kept in
# lockstep so this script only ever targets what the checker reports)
# ============================================================

def find_missing_days(records):
    dates = sorted({r.get("date") for r in records if r.get("date")})
    if not dates:
        return []

    d0 = date.fromisoformat(dates[0])
    d1 = date.fromisoformat(dates[-1])
    present = set(dates)

    missing = []
    d = d0
    while d <= d1:
        if d.isoformat() not in present:
            missing.append(d.isoformat())
        d += timedelta(days=1)

    return missing


def months_containing(missing_dates):
    """Return the distinct (year, month) pairs that need re-fetching,
    sorted oldest first."""
    months = sorted({(int(d[:4]), int(d[5:7])) for d in missing_dates})
    return months


# ============================================================
# SCRAPER -- STUBBED, see module docstring above.
# ============================================================

def fetch_month_history(year, month):
    """
    Fetch and parse ONE month of LiveChennai's daily gold-rate-history
    table. Must return a list of dicts shaped like:

        [
          {"date": "2023-08-01", "rate_22k": 5570, "rate_24k": 6037},
          ...
        ]

    Return an empty list (not None) if the month has no data or the
    fetch/parse fails -- callers treat that as "nothing to add", not
    as a fatal error, so one bad month doesn't stop the whole backfill.

    CURRENT STATE: not implemented for real. Every attempt to reach
    this page returned a table with header rows only (no <tr> data
    rows) -- see module docstring for what to check before filling
    this in. The shape below is a guess based on the *display*
    columns (Date | Pure Gold 24k | Standard Gold 22K) seen in the
    empty table's header; verify against real populated markup before
    trusting it.
    """
    print(
        f"  [SKIPPED] fetch_month_history({year}, {month}) is not "
        "implemented yet -- see the module docstring in "
        "backfill_history.py for what needs verifying before this "
        "can run for real."
    )
    return []

    # ---- reference sketch, once the real request shape is known ----
    #
    # params = {"monthno": month, "yearno": year}
    # res = SESSION.get(LIVECHENNAI_HISTORY_URL, params=params, timeout=REQUEST_TIMEOUT)
    # res.raise_for_status()
    # soup = BeautifulSoup(res.text, "html.parser")
    #
    # out = []
    # for table in soup.find_all("table"):
    #     rows = table.find_all("tr")
    #     if len(rows) < 2:
    #         continue
    #     header = rows[0].get_text(" ", strip=True).lower()
    #     if "date" not in header or "24" not in header:
    #         continue
    #     for row in rows[1:]:
    #         cells = row.find_all(["td", "th"])
    #         if len(cells) < 3:
    #             continue
    #         date_text = cells[0].get_text(" ", strip=True)
    #         rate22_text = cells[2].get_text(" ", strip=True)  # verify column index
    #         parsed_date = _parse_history_date(date_text, year, month)
    #         rate22 = _clean_number(rate22_text)
    #         if parsed_date and valid_gold_rate(rate22):
    #             out.append({
    #                 "date": parsed_date,
    #                 "rate_22k": int(rate22),
    #             })
    # return out


# ============================================================
# MERGE -- safe by construction: only adds records for dates that
# are (a) in the requested missing-dates set and (b) not already
# present in history.
# ============================================================

def merge_backfilled_records(existing_records, fetched, missing_dates_set):
    already_present = {r.get("date") for r in existing_records if r.get("date")}

    added = []
    skipped_not_missing = 0
    skipped_invalid = 0

    for rec in fetched:
        d = rec.get("date")
        rate = rec.get("rate_22k")

        if d not in missing_dates_set:
            # Fetched month may contain days we already have (e.g. the
            # month is only partially missing) -- never touch those.
            skipped_not_missing += 1
            continue

        if d in already_present:
            skipped_not_missing += 1
            continue

        if not valid_gold_rate(rate):
            skipped_invalid += 1
            continue

        rate = int(rate)
        new_rec = {
            "date": d,
            "rate_22k": rate,
            "rate_24k": rec.get("rate_24k") or round(rate * 24 / 22),
            "weight_1g": rate,
            "weight_8g": rate * 8,
            "source": "LiveChennai",
            "source_url": LIVECHENNAI_HISTORY_URL,
            "type": "daily_history_backfill",
        }
        added.append(new_rec)
        already_present.add(d)

    return added, skipped_not_missing, skipped_invalid


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        default="data/history.json",
        help="Path to history.json (default: data/history.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what's missing and which months would be fetched, but fetch/write nothing.",
    )
    args = parser.parse_args()

    history_path = Path(args.history)

    if not history_path.exists():
        print(f"ERROR: {history_path} not found")
        sys.exit(2)

    existing_data = load_json(history_path, [])
    existing_records = extract_history_records(existing_data)
    print(f"Loaded {len(existing_records)} existing records from {history_path}")

    missing = find_missing_days(existing_records)
    print(f"Missing calendar days: {len(missing)}")

    if not missing:
        print("Nothing to backfill.")
        return

    for d in missing:
        print(f"  - {d}")

    target_months = months_containing(missing)
    print(f"\nMonths to re-fetch: {len(target_months)}")
    for year, month in target_months:
        print(f"  - {year}-{month:02d}")

    if args.dry_run:
        print("\n--dry-run: stopping before any network calls or writes.")
        return

    missing_set = set(missing)
    all_added = []

    for year, month in target_months:
        print(f"\nFetching {year}-{month:02d}...")
        fetched = fetch_month_history(year, month)
        print(f"  Parsed {len(fetched)} records from that month's page")

        added, skipped_not_missing, skipped_invalid = merge_backfilled_records(
            existing_records, fetched, missing_set
        )

        print(
            f"  Added {len(added)}, skipped {skipped_not_missing} "
            f"(already present / not a target date), "
            f"skipped {skipped_invalid} (invalid rate)"
        )

        all_added.extend(added)
        existing_records.extend(added)

        time.sleep(REQUEST_DELAY_SECONDS)

    if not all_added:
        print("\nNo records were added (scraper not implemented, or nothing found).")
        return

    existing_records.sort(key=lambda r: (r.get("date") or "", r.get("time") or ""))

    if isinstance(existing_data, dict):
        existing_data["records"] = existing_records
        save_json(history_path, existing_data)
    else:
        save_json(history_path, existing_records)

    print(f"\nWrote {len(all_added)} new records to {history_path}")
    print("Re-run check_history_gaps.py to confirm the gaps are closed.")


if __name__ == "__main__":
    main()
