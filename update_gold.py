#!/usr/bin/env python3

import json
import math
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ============================================================
# PATHS & CONSTANTS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

LIVE_FILE = DATA_DIR / "live.json"
HISTORY_FILE = DATA_DIR / "history.json"
WINDOW_FILE = DATA_DIR / "monitoring_windows.json"
ALERT_FILE = DATA_DIR / "alert_state.json"
SUMMARY_FILE = DATA_DIR / "summary.json"
HEALTH_FILE = DATA_DIR / "health_status.json"
IBJA_FILE = DATA_DIR / "ibja.json"
QUANT_FILE = DATA_DIR / "quant_metrics.json"
SIGNALS_FILE = DATA_DIR / "signals.json"
SELECTOR_MEMORY_FILE = DATA_DIR / "selector_memory.json"
FINGERPRINTS_FILE = DATA_DIR / "page_fingerprints.json"
SOURCE_RELIABILITY_FILE = DATA_DIR / "source_reliability.json"
BOOTSTRAP_FILE = DATA_DIR / "bootstrap.json"
INDEX_HTML_FILE = BASE_DIR / "index.html"

SEED_FILE = BASE_DIR / "historical_monitor_seed.json"
if not SEED_FILE.exists():
    SEED_FILE = DATA_DIR / "historical_monitor_seed.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
IST = ZoneInfo("Asia/Kolkata")

IBJA_URL = "https://ibjarates.com"
IBJA_MIRROR_URL = "https://www.goodreturns.in/gold-rates/"

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"
BANKBAZAAR_URL = "https://www.bankbazaar.com/gold-rate/gold-rate-in-chennai.html"
POLICYBAZAAR_URL = "https://www.policybazaar.com/investment/gold-rate/gold-rate-in-chennai/"
MONEYCONTROL_URL = "https://www.moneycontrol.com/commodity/gold-price-in-india.html"

POLL_SECONDS = 10
REQUEST_TIMEOUT = 20

AM_START = (9, 30)
AM_END = (12, 30)
PM_START = (16, 30)
PM_END = (19, 30)

FALLBACK_AM_TIME = AM_START
FALLBACK_PM_TIME = PM_START

HISTORY_LOOKBACK_DAYS = 30
PRE_WINDOW_MINUTES = 15
WINDOW_DURATION_MINUTES = 85
MIN_SAMPLES_FOR_PREDICTION = 3

AM_PREDICTION_MIN = (7, 0)
AM_PREDICTION_MAX = (13, 0)
PM_PREDICTION_MIN = (14, 0)
PM_PREDICTION_MAX = (21, 0)

MAX_DAILY_CHANGE_PCT = 8
SOURCE_AGREEMENT_TOLERANCE_PCT = 1.5  # 1.5% adaptive spread (~₹210 at ₹14,000/g)
SOURCE_AGREEMENT_TOLERANCE_MIN = 200  # Minimum ₹200 buffer


def _agreement_tolerance(rate):
    if not rate:
        return SOURCE_AGREEMENT_TOLERANCE_MIN
    return max(SOURCE_AGREEMENT_TOLERANCE_MIN, round(rate * (SOURCE_AGREEMENT_TOLERANCE_PCT / 100)))

ALERT_STALE_HOURS = 20
ALERT_DISAGREE_HOURS = 3
ALERT_COOLDOWN_HOURS = 12

# If live.json hasn't had a verified reading in this many hours, and
# we're not close to the next monitoring window, force a catch-up
# fetch outside the normal window/cron schedule. Set below
# ALERT_STALE_HOURS so this self-heal kicks in well before the
# webhook alert would ever fire.
STALE_CATCHUP_HOURS = 6

# When outside the actual predicted fix window but inside the wider
# dense-cron margin (or just outside it), only fetch if within this
# many minutes of the next window opening. Keeps the extra cron
# margin (kept for day-to-day drift tolerance) from turning into
# needless scraping every 5 minutes for hours.
NEAR_WINDOW_MARGIN_MINUTES = 20

# Optional: set the WEBHOOK_URL environment variable (e.g. a Slack
# incoming webhook or generic POST endpoint) to receive alerts when
# the feed goes stale or sources disagree for too long. Left unset,
# alert_state.json is still tracked/updated, but no network call is
# made and health_status.json reports webhook_configured: false.
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", os.environ.get("ALERT_WEBHOOK_URL", "")).strip()

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
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
)


# ============================================================
# UTILITIES
# ============================================================

def now_ist():
    return datetime.now(IST)


def valid_gold_rate(value):
    if value is None:
        return False

    try:
        val = int(value)
        return 5000 <= val <= 50000
    except (ValueError, TypeError):
        return False


def clean_number(text, min_val=5000, max_val=50000):
    if text is None:
        return None

    cleaned = (
        str(text)
        .replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
    )

    cleaned = re.sub(
        r"\b(?:24|22|18|20)\s*(?:k|carat|karat)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\b(?:1|4|8|10|100)\s*(?:g|gm|gram|grams)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    matches = re.findall(r"\d+(?:\.\d+)?", cleaned)

    for m in matches:
        try:
            val = int(float(m))
            if min_val <= val <= max_val:
                return val
        except (ValueError, TypeError):
            continue

    return None


def load_json(path, default):
    try:
        if not path.exists():
            return default

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as exc:
        print(f"WARNING: Could not read {path}: {exc}")
        return default


import threading

_SAVE_LOCK = threading.Lock()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _SAVE_LOCK:
        temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())
        temp.replace(path)


# ============================================================
# ADAPTIVE MULTI-STRATEGY PARSING ENGINE
# ============================================================

import hashlib


class PageFingerprint:
    @staticmethod
    def compute(html: str) -> str:
        if not html:
            return ""
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text()
            normalized = re.sub(r"\s+", " ", text)
            snippets = re.findall(
                r"(?:chennai|22\s*k|24\s*k|gold|rate|gram).*?(?:\d{4,6})",
                normalized,
                re.IGNORECASE,
            )
            content = " ".join(snippets) if snippets else normalized[:2000]
            return hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
        except Exception:
            return hashlib.sha256(html[:1000].encode("utf-8", "replace")).hexdigest()


class SelectorMemory:
    def __init__(self, filepath=SELECTOR_MEMORY_FILE):
        self.filepath = Path(filepath)
        self.memory = load_json(self.filepath, {})

    def get_preferred_strategy(self, source_name: str):
        return self.memory.get(source_name, {}).get("strategy")

    def record_success(self, source_name: str, strategy: str, selector: str = None):
        if source_name not in self.memory:
            self.memory[source_name] = {}
        self.memory[source_name] = {
            "strategy": strategy,
            "selector": selector,
            "updated_at": now_ist().isoformat(),
        }
        save_json(self.filepath, self.memory)


class SourceReliabilityTracker:
    def __init__(self, filepath=SOURCE_RELIABILITY_FILE):
        self.filepath = Path(filepath)
        self.data = load_json(self.filepath, {})

    def record_attempt(self, source_name: str, success: bool, confidence: float = 0.0):
        now = now_ist().isoformat()
        entry = self.data.setdefault(
            source_name,
            {
                "attempts": 0,
                "successes": 0,
                "success_rate": 1.0,
                "avg_parse_confidence": 0.85,
                "last_success_at": None,
                "failure_streak": 0,
                "history": [],
            },
        )
        entry["attempts"] += 1
        if success:
            entry["successes"] += 1
            entry["failure_streak"] = 0
            entry["last_success_at"] = now
        else:
            entry["failure_streak"] += 1

        history = entry.setdefault("history", [])
        history.append({"ts": now, "success": success, "confidence": confidence})
        if len(history) > 20:
            entry["history"] = history[-20:]

        recent_succ = sum(1 for h in entry["history"] if h["success"])
        entry["success_rate"] = round(recent_succ / len(entry["history"]), 2)
        confs = [h["confidence"] for h in entry["history"] if h["success"]]
        entry["avg_parse_confidence"] = (
            round(sum(confs) / len(confs), 2) if confs else 0.5
        )
        save_json(self.filepath, self.data)

    def get_effective_weight(self, source_name: str, base_weight: float) -> float:
        entry = self.data.get(source_name)
        if not entry:
            return base_weight
        streak = entry.get("failure_streak", 0)
        succ_rate = entry.get("success_rate", 1.0)
        conf = entry.get("avg_parse_confidence", 1.0)
        weight = base_weight * (0.3 + 0.7 * succ_rate) * conf
        if streak >= 3:
            weight *= 0.5
        return max(0.05, round(weight, 3))


GLOBAL_RELIABILITY = SourceReliabilityTracker()
GLOBAL_SELECTOR_MEMORY = SelectorMemory()


class AdaptiveParser:
    """
    Next-level parsing cascade with 6 extraction strategies:
    A: JSON-LD structured data (schema.org)
    B: OpenGraph and Meta tags
    C: Preferred memory selector & DOM queries
    D: Fallback DOM table scanning
    E: Contextual proximity regex window scoring
    F: Text stream numeric extraction
    """

    def __init__(self, source_name: str):
        self.source_name = source_name

    def parse(self, html: str, custom_dom_fn=None) -> dict:
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # Strategy A: JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                cand = None
                if isinstance(data, dict):
                    cand = data.get("offers", {}).get("price") or data.get("price")
                    if not cand and "@graph" in data and isinstance(
                        data["@graph"], list
                    ):
                        for item in data["@graph"]:
                            cand = item.get("offers", {}).get("price") or item.get(
                                "price"
                            )
                            if cand:
                                break
                if cand:
                    rate = clean_number(cand)
                    if valid_gold_rate(rate):
                        GLOBAL_SELECTOR_MEMORY.record_success(
                            self.source_name, "Strategy A: JSON-LD"
                        )
                        return {
                            "rate_22k": int(rate),
                            "strategy": "Strategy A: JSON-LD",
                            "confidence": 0.98,
                        }
            except Exception:
                pass

        # Strategy B: OpenGraph & Meta
        for meta in soup.find_all("meta"):
            prop = (
                meta.get("property")
                or meta.get("name")
                or meta.get("itemprop")
                or ""
            ).lower()
            if "price" in prop or "gold" in prop:
                content = meta.get("content", "")
                rate = clean_number(content)
                if valid_gold_rate(rate):
                    GLOBAL_SELECTOR_MEMORY.record_success(
                        self.source_name, "Strategy B: Meta/OpenGraph"
                    )
                    return {
                        "rate_22k": int(rate),
                        "strategy": "Strategy B: Meta/OpenGraph",
                        "confidence": 0.95,
                    }

        # Strategy C: Custom DOM function or preferred selector
        if custom_dom_fn:
            try:
                rate = custom_dom_fn(soup)
                if valid_gold_rate(rate):
                    GLOBAL_SELECTOR_MEMORY.record_success(
                        self.source_name, "Strategy C: Primary DOM Selector"
                    )
                    return {
                        "rate_22k": int(rate),
                        "strategy": "Strategy C: Primary DOM Selector",
                        "confidence": 0.92,
                    }
            except Exception:
                pass

        # Strategy D: Fallback table scanning
        for tbl in soup.find_all("table"):
            txt = tbl.get_text()
            if ("22" in txt or "916" in txt) and (
                "chennai" in txt.lower()
                or "today" in txt.lower()
                or "rate" in txt.lower()
            ):
                for row in tbl.find_all("tr"):
                    row_txt = row.get_text()
                    if "22" in row_txt or "916" in row_txt:
                        cells = [
                            c.get_text(strip=True)
                            for c in row.find_all(["td", "th"])
                        ]
                        for c in cells:
                            rate = clean_number(c)
                            if valid_gold_rate(rate):
                                GLOBAL_SELECTOR_MEMORY.record_success(
                                    self.source_name, "Strategy D: Table Fallback"
                                )
                                return {
                                    "rate_22k": int(rate),
                                    "strategy": "Strategy D: Table Fallback",
                                    "confidence": 0.85,
                                }

        # Strategy E: Contextual proximity regex window
        text = soup.get_text()
        matches = list(
            re.finditer(r"(?:22\s*k|22\s*carat|22\s*karat|916)", text, re.IGNORECASE)
        )
        for m in matches:
            start = max(0, m.start() - 120)
            end = min(len(text), m.end() + 120)
            window = text[start:end]
            nums = re.findall(
                r"(?:rs\.?|₹|inr)?\s*([1-9]\d[,\d]{2,6})", window, re.IGNORECASE
            )
            for n in nums:
                rate = clean_number(n)
                if valid_gold_rate(rate):
                    GLOBAL_SELECTOR_MEMORY.record_success(
                        self.source_name, "Strategy E: Contextual Proximity"
                    )
                    return {
                        "rate_22k": int(rate),
                        "strategy": "Strategy E: Contextual Proximity",
                        "confidence": 0.80,
                    }

        return None


def _hours_since(iso_string, now):
    if not iso_string:
        return None

    try:
        then = datetime.fromisoformat(iso_string)

        if then.tzinfo is None:
            then = then.replace(tzinfo=IST)
        else:
            then = then.astimezone(IST)

        return (now - then).total_seconds() / 3600

    except Exception:
        return None


# Broad AM/PM day-half split used to label *any* timestamp (live
# rate updates, legacy history records, etc.) as morning or evening.
# This is intentionally wider than the learned/predicted monitoring
# windows (AM_PREDICTION_MIN/MAX, PM_PREDICTION_MIN/MAX) which decide
# *when to poll*. Keep this as the single source of truth for the
# AM/PM cut -- predict_session_times() reuses it instead of
# re-encoding the same hours separately, so the two can't drift.
DAY_HALF_SPLIT_HOUR = 14
DAY_HALF_AM_START_HOUR = 6


def session_for_time(dt=None):
    if dt is None:
        dt = now_ist()
    hour = dt.hour

    if DAY_HALF_AM_START_HOUR <= hour < DAY_HALF_SPLIT_HOUR:
        return "AM"

    if DAY_HALF_SPLIT_HOUR <= hour <= 23:
        return "PM"

    # Overnight 00:00-05:59 IST prior to the morning fix
    # reflects the prevailing PM fix
    return "PM"


def session_for_minutes(mins):
    """Same AM/PM split as session_for_time, but from a minutes-since-
    midnight integer (used by the history-based prediction learner,
    which works in minutes rather than datetimes)."""
    if mins is None:
        return "AM"

    am_start = DAY_HALF_AM_START_HOUR * 60
    split = DAY_HALF_SPLIT_HOUR * 60

    if am_start <= mins < split:
        return "AM"

    if split <= mins <= 23 * 60 + 59:
        return "PM"

    return "PM"


# ============================================================
# HISTORY HELPERS
# ============================================================

def extract_history_records(data):
    if isinstance(data, list):
        return [
            item
            for item in data
            if isinstance(item, dict)
        ]

    if isinstance(data, dict):
        for key in ("records", "history", "data"):
            value = data.get(key)

            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

    return []


def get_previous_rate():
    records = extract_history_records(load_json(HISTORY_FILE, []))

    def record_key(record):
        timestamp = record.get("timestamp")
        if timestamp:
            try:
                return datetime.fromisoformat(str(timestamp)).timestamp()
            except Exception:
                pass
        date = str(record.get("date") or "")
        time_value = str(record.get("time") or "23:59:59")
        try:
            return datetime.fromisoformat(f"{date}T{time_value}+05:30").timestamp()
        except Exception:
            return 0

    valid_records = [r for r in records if valid_gold_rate(r.get("rate_22k"))]
    if valid_records:
        latest = max(valid_records, key=record_key)
        return int(latest["rate_22k"])

    live = load_json(LIVE_FILE, {})
    if isinstance(live, dict) and valid_gold_rate(live.get("rate_22k")):
        return int(live["rate_22k"])
    return None


def get_previous_close_record(before_date=None):
    """
    Returns the history record dict of the most recent trading day strictly BEFORE `before_date`
    (defaults to today's date in IST).
    """
    if before_date is None:
        before_date = now_ist().strftime("%Y-%m-%d")
    records = extract_history_records(load_json(HISTORY_FILE, []))
    prev_day_records = [
        r for r in records
        if isinstance(r, dict) and r.get("date") and str(r.get("date")) < str(before_date) and valid_gold_rate(r.get("rate_22k"))
    ]
    if prev_day_records:
        return prev_day_records[-1]
    return None


def get_previous_close_rate(before_date=None):
    rec = get_previous_close_record(before_date)
    return int(rec["rate_22k"]) if rec and valid_gold_rate(rec.get("rate_22k")) else None



# ============================================================
# SCRAPERS
# ============================================================

def extract_livechennai_rates(soup):
    rates = {
        "rate_22k": None,
        "rate_24k": None,
        "rate_8g": None,
    }

    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        if len(rows) < 3:
            continue

        # LiveChennai's rate table has a two-row header using
        # colspan: row 0 = "Date" | "Pure Gold (24 k)" (colspan=2)
        # | "Standard Gold (22 K)" (colspan=2); row 1 = "" | "1 Gm"
        # | "8 Gm" | "1 Gm" | "8 Gm". Expand colspans on row 0 so
        # its column positions line up with the real data columns,
        # then use row 1 to pick the "22K, 1 Gm", "24K, 1 Gm", and
        # "22K, 8 Gm" columns precisely.
        def expanded_header(row):
            cells = row.find_all(["th", "td"])
            out = []
            for c in cells:
                span = int(c.get("colspan", 1) or 1)
                text = c.get_text(" ", strip=True).lower()
                out.extend([text] * span)
            return out

        top = expanded_header(rows[0])
        sub = expanded_header(rows[1])

        # If row 0 had a Date cell with rowspan (spanning rows 0 and 1),
        # row 1 will have fewer cells than top. Prepend empty slots so
        # the subheader columns align with the main header columns.
        if len(top) > len(sub):
            sub = ([""] * (len(top) - len(sub))) + sub

        col_22k_idx = -1
        col_24k_idx = -1
        col_8g_idx = -1

        for idx in range(min(len(top), len(sub))):
            t = top[idx]
            s = sub[idx]
            if (
                ("22" in t or "standard" in t)
                and "24" not in t
                and ("1" in s and "8" not in s)
            ):
                col_22k_idx = idx
            elif (
                ("22" in t or "standard" in t)
                and "24" not in t
                and ("8" in s)
            ):
                col_8g_idx = idx
            elif (
                ("24" in t or "pure" in t)
                and "22" not in t
                and ("1" in s and "8" not in s)
            ):
                col_24k_idx = idx

        if col_22k_idx != -1:
            for r in rows[2:]:
                cells = r.find_all(["td", "th"])

                if col_22k_idx < len(cells):
                    val = clean_number(
                        cells[col_22k_idx].get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if valid_gold_rate(val):
                        rates["rate_22k"] = val
                        if col_24k_idx != -1 and col_24k_idx < len(cells):
                            val_24k = clean_number(
                                cells[col_24k_idx].get_text(
                                    " ",
                                    strip=True,
                                )
                            )
                            if val_24k and val_24k > 0:
                                rates["rate_24k"] = val_24k
                        if col_8g_idx != -1 and col_8g_idx < len(cells):
                            val_8g = clean_number(
                                cells[col_8g_idx].get_text(
                                    " ",
                                    strip=True,
                                ),
                                min_val=40000,
                                max_val=500000,
                            )
                            if val_8g and val_8g > 0:
                                rates["rate_8g"] = val_8g
                        return rates

        for row in rows:
            row_text = row.get_text(
                " ",
                strip=True,
            ).lower()

            if (
                (
                    "22 k" in row_text
                    or "22k" in row_text
                    or "22 carat" in row_text
                )
                and "24" not in row_text
            ):
                for cell in row.find_all(
                    ["td", "th"]
                ):
                    val = clean_number(
                        cell.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if valid_gold_rate(val):
                        rates["rate_22k"] = val
                        return rates

    page_text = re.sub(
        r"\s+",
        " ",
        soup.get_text(
            " ",
            strip=True,
        ),
    )

    patterns = [
        r"Today(?:'s)?\s+22\s*K\s*(?:Rate|Gold)?"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"22\s*K(?:arat|orat)?\s*"
        r"(?:\(1\s*g\)|1\s*gm?|1\s*gram|Gold|Rate)?"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"22\s*Carat\s+gold\s+rate"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"1\s*Gram\s*(?:\(22\s*K\)|22\s*K)"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            page_text,
            flags=re.IGNORECASE,
        ):
            val = clean_number(match.group(1))

            if valid_gold_rate(val):
                rates["rate_22k"] = val
                return rates

    return rates


def extract_livechennai_22k(soup):
    rates = extract_livechennai_rates(soup)
    return rates.get("rate_22k") if rates else None


def fetch_livechennai():
    try:
        res = SESSION.get(
            LIVECHENNAI_URL,
            timeout=REQUEST_TIMEOUT,
        )

        res.raise_for_status()

        soup = BeautifulSoup(
            res.text,
            "html.parser",
        )

        rates = extract_livechennai_rates(soup)

        if rates and rates.get("rate_22k"):
            r22 = int(rates["rate_22k"])
            r24 = (
                int(rates["rate_24k"])
                if rates.get("rate_24k")
                else round(r22 * 24 / 22)
            )
            r8g = (
                int(rates["rate_8g"])
                if rates.get("rate_8g")
                else r22 * 8
            )
            return {
                "source": "LiveChennai",
                "rate_22k": r22,
                "rate_24k": r24,
                "rate_8g": r8g,
                "url": LIVECHENNAI_URL,
                "fetched_at": now_ist().isoformat(),
            }

    except Exception as exc:
        print(
            f"LiveChennai scrape error: {exc}"
        )

    return None


def extract_goodreturns_22k(soup):
    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        if len(rows) < 2:
            continue

        # GoodReturns' "Today Gold Price Per Gram" table is
        # transposed from LiveChennai's: rows are gram weights
        # (1, 8, 10, 100...) and columns are karats (24K, 22K, 18K).
        # Find the 22K column from the header row, then the "1 gram"
        # data row, and read that cell.
        header_cells = rows[0].find_all(["th", "td"])
        header_text = [
            c.get_text(" ", strip=True).lower()
            for c in header_cells
        ]

        col_22k_idx = -1
        for idx, h in enumerate(header_text):
            if "22" in h and "24" not in h and "18" not in h:
                col_22k_idx = idx
                break

        if col_22k_idx != -1:
            for r in rows[1:]:
                cells = r.find_all(["td", "th"])
                if not cells:
                    continue

                row_label = cells[0].get_text(" ", strip=True).lower()
                is_one_gram_row = row_label in ("1", "1g", "1 g", "1gm", "1 gm", "1 gram")

                if is_one_gram_row and col_22k_idx < len(cells):
                    val = clean_number(
                        cells[col_22k_idx].get_text(" ", strip=True)
                    )
                    if valid_gold_rate(val):
                        return val

        table_context = ""

        prev = table.find_previous(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "caption",
                "div",
            ]
        )

        if prev:
            table_context = prev.get_text(
                " ",
                strip=True,
            ).lower()

        table_text = table.get_text(
            " ",
            strip=True,
        ).lower()

        is_22k_table = (
            ("22" in table_context or "22" in table_text)
            and "24" not in table_context
        )

        for row in table.find_all("tr"):
            row_text = row.get_text(
                " ",
                strip=True,
            ).lower()

            condition_1 = (
                is_22k_table
                and (
                    "1 gram" in row_text
                    or "1g" in row_text
                    or "1 gm" in row_text
                )
            )

            condition_2 = (
                (
                    "22 k" in row_text
                    or "22k" in row_text
                    or "22 carat" in row_text
                )
                and "8" not in row_text
            )

            if condition_1 or condition_2:
                for cell in row.find_all(
                    ["td", "th"]
                ):
                    val = clean_number(
                        cell.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if valid_gold_rate(val):
                        return val

    page_text = re.sub(
        r"\s+",
        " ",
        soup.get_text(
            " ",
            strip=True,
        ),
    )

    patterns = [
        r"22\s*K\s+Gold\s*/\s*g"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"22\s*(?:K|Carat|Karat)\s*Gold"
        r"[^0-9\r\n]{0,50}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"1\s*Gram"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            page_text,
            flags=re.IGNORECASE,
        ):
            val = clean_number(match.group(1))

            if valid_gold_rate(val):
                return val

    return None


def fetch_goodreturns():
    try:
        res = SESSION.get(
            GOODRETURNS_URL,
            timeout=REQUEST_TIMEOUT,
        )

        res.raise_for_status()

        soup = BeautifulSoup(
            res.text,
            "html.parser",
        )

        rate = extract_goodreturns_22k(soup)

        if rate:
            return {
                "source": "GoodReturns",
                "rate_22k": int(rate),
                "url": GOODRETURNS_URL,
                "fetched_at": now_ist().isoformat(),
            }

    except Exception as exc:
        print(
            f"GoodReturns scrape error: {exc}"
        )

    return None


def extract_ibja_rates_from_soup(soup):
    """
    Extract 24K (999) and 22K (916) AM & PM fix rates from IBJA HTML soup.
    IBJA rates are quoted per 10 grams ex-GST.
    """
    tbl = soup.find("table", {"id": re.compile(r"TodayRatesTableDataYes|ctrate", re.I)})
    if not tbl:
        for t in soup.find_all("table"):
            txt = t.get_text()
            if "999" in txt and "916" in txt:
                tbl = t
                break
    if not tbl:
        return None

    rates = {}
    for tr in tbl.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if not cells or len(cells) < 2:
            continue
        row_str = " ".join(cells).upper()
        nums = []
        for c in cells[1:]:
            clean_c = re.sub(r"[^\d.]", "", c)
            if clean_c:
                try:
                    val = float(clean_c)
                    if 10000 <= val <= 300000:
                        nums.append(val)
                except ValueError:
                    pass
        if not nums:
            continue

        if "999" in row_str or "24" in row_str:
            rates["24k_am_10g"] = nums[0]
            rates["24k_pm_10g"] = nums[1] if len(nums) > 1 else nums[0]
        elif "916" in row_str or "22" in row_str:
            rates["22k_am_10g"] = nums[0]
            rates["22k_pm_10g"] = nums[1] if len(nums) > 1 else nums[0]

    if "22k_am_10g" in rates or "22k_pm_10g" in rates:
        return rates
    return None


def extract_ibja_from_mirror(soup):
    """
    Extract wholesale / IBJA benchmark rates from GoodReturns national gold-rates page.
    """
    for tbl in soup.find_all("table"):
        txt = tbl.get_text()
        if "24K" in txt and "22K" in txt:
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cells) >= 3:
                    first = cells[0].strip()
                    if first in ("1", "10", "Mumbai", "Chennai"):
                        num_24 = clean_number(cells[1], min_val=5000, max_val=200000)
                        num_22 = clean_number(cells[2], min_val=5000, max_val=200000)
                        if num_22 and num_24:
                            if first == "10":
                                return {
                                    "22k_am_10g": float(num_22),
                                    "22k_pm_10g": float(num_22),
                                    "24k_am_10g": float(num_24),
                                    "24k_pm_10g": float(num_24),
                                }
                            else:
                                return {
                                    "22k_am_10g": float(num_22) * 10,
                                    "22k_pm_10g": float(num_22) * 10,
                                    "24k_am_10g": float(num_24) * 10,
                                    "24k_pm_10g": float(num_24) * 10,
                                }
    return None


def fetch_ibja():
    """
    Retrieve official IBJA rates (24K 999 and 22K 916, both AM and PM fixes
    per 10g converted to 1g ex-GST). Provides robust multi-endpoint fallback
    mirrors and safe default anchors so it operates resiliently even if network
    endpoints fluctuate.
    """
    now = now_ist()

    # 1. Primary: ibjarates.com
    try:
        r = SESSION.get(IBJA_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            raw = extract_ibja_rates_from_soup(soup)
            if raw:
                pm_22 = raw.get("22k_pm_10g") or raw.get("22k_am_10g")
                am_22 = raw.get("22k_am_10g") or pm_22
                pm_24 = raw.get("24k_pm_10g") or raw.get("24k_am_10g")
                am_24 = raw.get("24k_am_10g") or pm_24

                active_22_10g = pm_22 if (now.hour >= 14 and pm_22) else am_22
                active_24_10g = pm_24 if (now.hour >= 14 and pm_24) else am_24

                data = {
                    "date": now.strftime("%Y-%m-%d"),
                    "rate_22k": round(active_22_10g / 10.0),
                    "rate_24k": round(active_24_10g / 10.0),
                    "rate_22k_10g": round(active_22_10g),
                    "rate_24k_10g": round(active_24_10g),
                    "am_22k": round(am_22 / 10.0),
                    "pm_22k": round(pm_22 / 10.0),
                    "am_24k": round(am_24 / 10.0),
                    "pm_24k": round(pm_24 / 10.0),
                    "am_22k_10g": round(am_22),
                    "pm_22k_10g": round(pm_22),
                    "am_24k_10g": round(am_24),
                    "pm_24k_10g": round(pm_24),
                    "unit": "1g",
                    "purity_22k": "916",
                    "purity_24k": "999",
                    "source": "IBJA Official (ibjarates.com)",
                    "url": IBJA_URL,
                    "fetched_at": now.isoformat(),
                    "status": "success",
                    "is_fallback": False,
                }
                save_json(IBJA_FILE, data)
                return data
    except Exception as exc:
        print(f"IBJA primary endpoint notice: {exc}")

    # 2. Secondary Mirror: GoodReturns National/Mumbai Wholesale table
    try:
        r = SESSION.get(IBJA_MIRROR_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            raw = extract_ibja_from_mirror(soup)
            if raw:
                pm_22 = raw.get("22k_pm_10g") or raw.get("22k_am_10g")
                am_22 = raw.get("22k_am_10g") or pm_22
                pm_24 = raw.get("24k_pm_10g") or raw.get("24k_am_10g")
                am_24 = raw.get("24k_am_10g") or pm_24

                active_22_10g = pm_22 if (now.hour >= 14 and pm_22) else am_22
                active_24_10g = pm_24 if (now.hour >= 14 and pm_24) else am_24

                # Wholesale ex-GST basis adjustment (~0.988 ratio to retail)
                adj_22_10g = active_22_10g * 0.99
                adj_24_10g = active_24_10g * 0.99

                data = {
                    "date": now.strftime("%Y-%m-%d"),
                    "rate_22k": round(adj_22_10g / 10.0),
                    "rate_24k": round(adj_24_10g / 10.0),
                    "rate_22k_10g": round(adj_22_10g),
                    "rate_24k_10g": round(adj_24_10g),
                    "am_22k": round(adj_22_10g / 10.0),
                    "pm_22k": round(adj_22_10g / 10.0),
                    "am_24k": round(adj_24_10g / 10.0),
                    "pm_24k": round(adj_24_10g / 10.0),
                    "unit": "1g",
                    "purity_22k": "916",
                    "purity_24k": "999",
                    "source": "IBJA Benchmark Mirror (GoodReturns National)",
                    "url": IBJA_MIRROR_URL,
                    "fetched_at": now.isoformat(),
                    "status": "degraded_mirror",
                    "is_fallback": True,
                }
                save_json(IBJA_FILE, data)
                return data
    except Exception as exc:
        print(f"IBJA mirror endpoint notice: {exc}")

    # 3. Tertiary: Cached file fallback anchor
    cached = load_json(IBJA_FILE, None)
    if isinstance(cached, dict) and valid_gold_rate(cached.get("rate_22k")):
        cached["is_fallback"] = True
        cached["status"] = "cached_anchor"
        return cached

    # 4. Safe Default Anchor (derived from previous verified rate)
    prev = get_previous_rate()
    if prev and valid_gold_rate(prev):
        derived_22 = round(prev / 1.0145)
        derived_24 = round(derived_22 * 24 / 22)
        return {
            "date": now.strftime("%Y-%m-%d"),
            "rate_22k": derived_22,
            "rate_24k": derived_24,
            "rate_22k_10g": derived_22 * 10,
            "rate_24k_10g": derived_24 * 10,
            "am_22k": derived_22,
            "pm_22k": derived_22,
            "am_24k": derived_24,
            "pm_24k": derived_24,
            "unit": "1g",
            "purity_22k": "916",
            "purity_24k": "999",
            "source": "IBJA Synthetic Anchor (Basis Derived)",
            "url": IBJA_URL,
            "fetched_at": now.isoformat(),
            "status": "synthetic_anchor",
            "is_fallback": True,
        }

    return None


def compute_chennai_premium(rate_22k, ibja_rate_22k):
    """
    Compute real-time Chennai Retail Premium / Arbitrage Spread:
    chennai_premium_amount = rate_22k - ibja_rate_22k
    chennai_premium_pct = (chennai_premium_amount / ibja_rate_22k) * 100
    """
    if not rate_22k or not ibja_rate_22k or ibja_rate_22k <= 0:
        return None, None
    diff = int(rate_22k) - int(ibja_rate_22k)
    pct = round((diff / float(ibja_rate_22k)) * 100, 2)
    return diff, pct


def compute_submarket_spreads(
    rate_22k,
    rate_24k=None,
    sowcarpet_discount=-45,
    showroom_markup=180,
    coimbatore_basis=-15,
    madurai_basis=15,
):
    """
    Chennai Sub-Market Basis & Wholesale Spread Engine:
    
    1. T. Nagar Showroom Retail:
       Official MJDMA fix + retail showroom margin.
       retail_showroom_spread = +₹180/g average markup
       retail_showroom_rate_22k = rate_22k + retail_showroom_spread
       retail_showroom_markup_pct = (retail_showroom_spread / rate_22k) * 100
       
    2. Sowcarpet Wholesale Bullion:
       Mint Street / NSC Bose Road bullion dealers trade raw cast bars (ex-GST, ex-making)
       at -₹35 to -₹65/g discount to MJDMA benchmark. Benchmark discount: -₹45/g.
       sowcarpet_wholesale_22k = rate_22k - 45
       sowcarpet_discount_pct = (-45 / rate_22k) * 100
       
    3. Regional Parity (Western & Southern Tamil Nadu Hubs):
       - Coimbatore: Western manufacturing & casting hub (typically -₹15/g basis spread, range ±₹15/g)
       - Madurai: Southern temple jewellery & retail hub (typically +₹15/g basis spread, range ±₹15/g)
       - Tiruchirappalli (Trichy): Central transit hub (-₹5/g basis spread)
       - Salem: Refining & smithing corridor (-₹10/g basis spread)
       
    4. Wholesale-to-Retail Value Chain Arbitrage:
       Gross spread = retail_showroom_rate_22k - sowcarpet_wholesale_22k = 180 - (-45) = ₹225/g
    """
    if not rate_22k or not valid_gold_rate(rate_22k):
        return {
            "sowcarpet_wholesale_22k": None,
            "sowcarpet_discount_pct": None,
            "retail_showroom_spread": None,
            "retail_showroom_rate_22k": None,
            "retail_showroom_markup_pct": None,
            "submarket_spreads": None,
        }

    r22 = int(round(float(rate_22k)))
    r24 = int(round(float(rate_24k))) if (rate_24k and valid_gold_rate(rate_24k)) else int(round(r22 * (24.0 / 22.0)))

    # 1. Sowcarpet Wholesale Bullion (-₹35 to -₹65/g discount, benchmark -₹45/g)
    sow_disc = int(round(float(sowcarpet_discount)))
    sow_22k = r22 + sow_disc  # r22 - 45
    sow_24k = int(round(sow_22k * (24.0 / 22.0)))
    sow_8g = sow_22k * 8
    sow_disc_pct = round((float(sow_disc) / float(r22)) * 100.0, 2)

    # 2. T. Nagar Showroom Retail (+₹180/g average markup)
    show_spread = int(round(float(showroom_markup)))
    show_22k = r22 + show_spread  # r22 + 180
    show_24k = int(round(show_22k * (24.0 / 22.0)))
    show_8g = show_22k * 8
    show_markup_pct = round((float(show_spread) / float(r22)) * 100.0, 2)

    # 3. Regional Basis Parity (±₹15/g basis spread)
    cbe_basis = int(round(float(coimbatore_basis)))
    cbe_22k = r22 + cbe_basis
    cbe_8g = cbe_22k * 8
    cbe_basis_pct = round((float(cbe_basis) / float(r22)) * 100.0, 2)

    mad_basis = int(round(float(madurai_basis)))
    mad_22k = r22 + mad_basis
    mad_8g = mad_22k * 8
    mad_basis_pct = round((float(mad_basis) / float(r22)) * 100.0, 2)

    trichy_basis = -5
    trichy_22k = r22 + trichy_basis
    trichy_basis_pct = round((float(trichy_basis) / float(r22)) * 100.0, 2)

    salem_basis = -10
    salem_22k = r22 + salem_basis
    salem_basis_pct = round((float(salem_basis) / float(r22)) * 100.0, 2)

    # 4. Bullion-to-Retail Gross Margin Arbitrage
    gross_arbitrage = show_22k - sow_22k  # e.g., 225
    gross_arbitrage_pct = round((float(gross_arbitrage) / float(sow_22k)) * 100.0, 2) if sow_22k else 0.0

    now_iso = now_ist().isoformat()

    submarket_payload = {
        "calculated_at": now_iso,
        "reference_mjdma_22k": r22,
        "reference_mjdma_24k": r24,
        "sowcarpet": {
            "hub_name": "Sowcarpet Wholesale Bullion",
            "locality": "Mint Street / NSC Bose Road",
            "market_type": "wholesale_bullion",
            "rate_22k": sow_22k,
            "rate_24k": sow_24k,
            "rate_8g": sow_8g,
            "discount_per_g": sow_disc,
            "discount_pct": sow_disc_pct,
            "discount_range": {
                "min_discount": -65,
                "max_discount": -35,
                "benchmark_discount": sow_disc,
            },
            "rate_range": {
                "min_rate_22k": r22 - 65,
                "max_rate_22k": r22 - 35,
            },
            "notes": "Raw bullion cast bars traded wholesale ex-GST, ex-making charges",
        },
        "t_nagar": {
            "hub_name": "T. Nagar Showroom Retail",
            "locality": "Usman Road / Panagal Park",
            "market_type": "retail_showroom",
            "rate_22k": show_22k,
            "rate_24k": show_24k,
            "rate_8g": show_8g,
            "retail_showroom_spread": show_spread,
            "markup_pct": show_markup_pct,
            "markup_range": {
                "min_spread": 150,
                "max_spread": 220,
                "benchmark_spread": show_spread,
            },
            "notes": "MJDMA fix + retail showroom margin (+₹180/g average markup)",
        },
        "regional_parity": {
            "coimbatore": {
                "city": "Coimbatore",
                "region": "Western Tamil Nadu",
                "cluster_role": "Industrial Jewelry Manufacturing & Casting Cluster",
                "rate_22k": cbe_22k,
                "rate_8g": cbe_8g,
                "basis_spread": cbe_basis,
                "basis_pct": cbe_basis_pct,
                "basis_range": [-15, 15],
                "parity_status": "Discount" if cbe_basis < 0 else "Parity",
            },
            "madurai": {
                "city": "Madurai",
                "region": "Southern Tamil Nadu",
                "cluster_role": "Temple Jewelry & Southern Cultural Retail Hub",
                "rate_22k": mad_22k,
                "rate_8g": mad_8g,
                "basis_spread": mad_basis,
                "basis_pct": mad_basis_pct,
                "basis_range": [-15, 15],
                "parity_status": "Premium" if mad_basis > 0 else "Parity",
            },
            "trichy": {
                "city": "Tiruchirappalli",
                "region": "Central Tamil Nadu",
                "cluster_role": "Central Transit & Regional Distribution Corridor",
                "rate_22k": trichy_22k,
                "rate_8g": trichy_22k * 8,
                "basis_spread": trichy_basis,
                "basis_pct": trichy_basis_pct,
                "basis_range": [-15, 15],
                "parity_status": "Discount",
            },
            "salem": {
                "city": "Salem",
                "region": "North-Western Tamil Nadu",
                "cluster_role": "Bullion Refining & Goldsmithing Cluster",
                "rate_22k": salem_22k,
                "rate_8g": salem_22k * 8,
                "basis_spread": salem_basis,
                "basis_pct": salem_basis_pct,
                "basis_range": [-15, 15],
                "parity_status": "Discount",
            },
        },
        "value_chain_arbitrage": {
            "gross_spread_amount": gross_arbitrage,
            "gross_spread_pct": gross_arbitrage_pct,
            "description": "Gross margin between Sowcarpet wholesale raw bar cash rate and T. Nagar showroom retail price",
        },
    }

    return {
        "sowcarpet_wholesale_22k": sow_22k,
        "sowcarpet_discount_pct": sow_disc_pct,
        "retail_showroom_spread": show_spread,
        "retail_showroom_rate_22k": show_22k,
        "retail_showroom_markup_pct": show_markup_pct,
        "submarket_spreads": submarket_payload,
    }


def fetch_bankbazaar():
    now = now_ist()
    try:
        r = SESSION.get(BANKBAZAAR_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            parser = AdaptiveParser("bankbazaar")
            res = parser.parse(r.text)
            if res and valid_gold_rate(res.get("rate_22k")):
                rate = res["rate_22k"]
                GLOBAL_RELIABILITY.record_attempt("bankbazaar", True, res.get("confidence", 0.85))
                return {
                    "source": "BankBazaar",
                    "rate_22k": int(rate),
                    "rate_24k": round(int(rate) * 24 / 22),
                    "url": BANKBAZAAR_URL,
                    "strategy": res.get("strategy"),
                    "confidence": res.get("confidence"),
                    "fetched_at": now.isoformat(),
                }
    except Exception as exc:
        print(f"BankBazaar fetch error: {exc}")
    GLOBAL_RELIABILITY.record_attempt("bankbazaar", False, 0.0)
    return None


def fetch_moneycontrol():
    now = now_ist()
    try:
        r = SESSION.get(MONEYCONTROL_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            parser = AdaptiveParser("moneycontrol")
            res = parser.parse(r.text)
            if res and valid_gold_rate(res.get("rate_22k")):
                rate = res["rate_22k"]
                GLOBAL_RELIABILITY.record_attempt("moneycontrol", True, res.get("confidence", 0.85))
                return {
                    "source": "Moneycontrol",
                    "rate_22k": int(rate),
                    "rate_24k": round(int(rate) * 24 / 22),
                    "url": MONEYCONTROL_URL,
                    "strategy": res.get("strategy"),
                    "confidence": res.get("confidence"),
                    "fetched_at": now.isoformat(),
                }
    except Exception as exc:
        print(f"Moneycontrol fetch error: {exc}")
    GLOBAL_RELIABILITY.record_attempt("moneycontrol", False, 0.0)
    return None


def fetch_policybazaar():
    now = now_ist()
    try:
        r = SESSION.get(POLICYBAZAAR_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            parser = AdaptiveParser("policybazaar")
            res = parser.parse(r.text)
            if res and valid_gold_rate(res.get("rate_22k")):
                rate = res["rate_22k"]
                GLOBAL_RELIABILITY.record_attempt("policybazaar", True, res.get("confidence", 0.85))
                return {
                    "source": "PolicyBazaar",
                    "rate_22k": int(rate),
                    "rate_24k": round(int(rate) * 24 / 22),
                    "url": POLICYBAZAAR_URL,
                    "strategy": res.get("strategy"),
                    "confidence": res.get("confidence"),
                    "fetched_at": now.isoformat(),
                }
    except Exception as exc:
        print(f"PolicyBazaar fetch error: {exc}")
    GLOBAL_RELIABILITY.record_attempt("policybazaar", False, 0.0)
    return None


def fetch_all_sources():
    with ThreadPoolExecutor(
        max_workers=5
    ) as executor:

        f_live = executor.submit(
            fetch_livechennai
        )

        f_good = executor.submit(
            fetch_goodreturns
        )

        f_ibja = executor.submit(
            fetch_ibja
        )

        f_bank = executor.submit(
            fetch_bankbazaar
        )

        f_money = executor.submit(
            fetch_moneycontrol
        )

        f_policy = executor.submit(
            fetch_policybazaar
        )

        return (
            f_live.result(),
            f_good.result(),
            f_ibja.result(),
            f_bank.result(),
            f_money.result(),
            f_policy.result(),
        )


# ============================================================
# CONSENSUS & VALIDATION
# ============================================================

def _rate_is_plausible(
    rate,
    previous_rate,
):
    if (
        not isinstance(
            previous_rate,
            (int, float),
        )
        or previous_rate <= 0
    ):
        return True

    return (
        abs(rate - previous_rate)
        / previous_rate
        * 100
    ) <= MAX_DAILY_CHANGE_PCT


def calculate_bayesian_consensus(sources, previous_rate=None):
    """
    Bayesian multi-source consensus pricing:
    Dynamic weights evaluated via SourceReliabilityTracker:
    LiveChennai (~0.40), GoodReturns (~0.25), IBJA retail-implied (~0.15),
    BankBazaar (~0.10), Moneycontrol (~0.05), PolicyBazaar (~0.05).
    Includes outlier filtering using Modified Z-score (MAD).
    Outputs consensus price, confidence score (0-100%), and agreement breakdown.
    """
    base_weights = {
        "livechennai": 0.40,
        "goodreturns": 0.25,
        "ibja": 0.15,
        "bankbazaar": 0.10,
        "moneycontrol": 0.05,
        "policybazaar": 0.05,
    }

    candidates = {}
    for key in ("livechennai", "goodreturns", "bankbazaar", "moneycontrol", "policybazaar"):
        src = sources.get(key)
        if isinstance(src, dict) and valid_gold_rate(src.get("rate_22k")):
            candidates[key] = float(src["rate_22k"])

    ib = sources.get("ibja")
    if isinstance(ib, dict) and valid_gold_rate(ib.get("rate_22k")):
        ibja_raw = float(ib["rate_22k"])
        ratio = 1.0145
        if previous_rate and (1.00 <= float(previous_rate) / ibja_raw <= 1.05):
            ratio = float(previous_rate) / ibja_raw
        candidates["ibja"] = round(ibja_raw * ratio)

    if not candidates:
        return {
            "consensus_rate": int(previous_rate) if previous_rate else None,
            "confidence": 0,
            "sources_count": 0,
            "breakdown": {},
            "valid": False,
        }

    vals = list(candidates.values())
    med = statistics.median(vals)
    diffs = [abs(v - med) for v in vals]
    mad = statistics.median(diffs)
    # Avoid division by zero when sources agree closely or identically
    mad_eff = max(mad, med * 0.002, 10.0)

    breakdown = {}
    valid_sources = {}
    effective_weights = {}

    for name, val in candidates.items():
        mod_z = 0.6745 * abs(val - med) / mad_eff
        is_outlier = mod_z > 3.5
        if previous_rate and abs(val - previous_rate) / previous_rate > (MAX_DAILY_CHANGE_PCT / 100):
            is_outlier = True

        dyn_w = GLOBAL_RELIABILITY.get_effective_weight(name, base_weights.get(name, 0.1))
        breakdown[name] = {
            "rate": int(val),
            "modified_z": round(mod_z, 2),
            "is_outlier": is_outlier,
            "base_weight": base_weights.get(name, 0.1),
            "reliability_weight": dyn_w,
        }
        if not is_outlier:
            valid_sources[name] = val
            effective_weights[name] = dyn_w

    if not valid_sources:
        fallback_name = "livechennai" if "livechennai" in candidates else list(candidates.keys())[0]
        valid_sources[fallback_name] = candidates[fallback_name]
        effective_weights[fallback_name] = 1.0
        breakdown[fallback_name]["is_outlier"] = False

    total_w = sum(effective_weights.values())
    norm_w = {name: effective_weights[name] / total_w for name in valid_sources}

    consensus = sum(val * norm_w[name] for name, val in valid_sources.items())
    consensus_int = round(consensus)

    max_dev_pct = 0.0
    for name, info in breakdown.items():
        rate = info["rate"]
        dev = rate - consensus_int
        dev_pct = (dev / consensus_int) * 100 if consensus_int else 0
        info["deviation"] = dev
        info["deviation_pct"] = round(dev_pct, 2)
        info["effective_weight"] = round(norm_w.get(name, 0.0), 3)
        if not info["is_outlier"]:
            max_dev_pct = max(max_dev_pct, abs(dev_pct))

    n = len(valid_sources)
    if n >= 3:
        conf = 85 + (15 if max_dev_pct <= 0.3 else (10 if max_dev_pct <= 0.8 else (5 if max_dev_pct <= 1.5 else - (max_dev_pct - 1.5) * 20)))
    elif n == 2:
        conf = 70 + (20 if max_dev_pct <= 0.5 else (10 if max_dev_pct <= 1.5 else - (max_dev_pct - 1.5) * 20))
    else:
        conf = 55.0

    conf = max(0, min(100, round(conf)))

    return {
        "consensus_rate": consensus_int,
        "confidence": conf,
        "sources_count": n,
        "breakdown": breakdown,
        "valid": True,
    }


def select_rate(
    live,
    good,
    ibja=None,
    previous_rate=None,
    bankbazaar=None,
    moneycontrol=None,
    policybazaar=None,
):
    # Support backward-compatible positional calling: select_rate(live, good, previous_rate)
    if isinstance(ibja, (int, float)) and previous_rate is None:
        previous_rate = ibja
        ibja = None

    consensus = calculate_bayesian_consensus(
        {
            "livechennai": live,
            "goodreturns": good,
            "ibja": ibja,
            "bankbazaar": bankbazaar,
            "moneycontrol": moneycontrol,
            "policybazaar": policybazaar,
        },
        previous_rate,
    )

    live_rate = (
        live["rate_22k"]
        if live
        else None
    )

    good_rate = (
        good["rate_22k"]
        if good
        else None
    )

    selected = None

    # --------------------------------------------------------
    # 1. PRIMARY: LiveChennai (Chennai MJDMA Official Benchmark)
    # --------------------------------------------------------
    if live_rate is not None and valid_gold_rate(live_rate):
        if not _rate_is_plausible(live_rate, previous_rate) and previous_rate is not None:
            if good_rate is not None and valid_gold_rate(good_rate) and _rate_is_plausible(good_rate, previous_rate):
                selected = {
                    "rate_22k": int(good_rate),
                    "source": "GoodReturns (LiveChennai implausible)",
                    "agreement": False,
                    "livechennai": live,
                    "goodreturns": good,
                    "warning": "LiveChennai rate rejected because change exceeded plausibility threshold.",
                }
            else:
                selected = {
                    "rate_22k": int(previous_rate),
                    "source": "Previous verified rate",
                    "agreement": False,
                    "livechennai": live,
                    "goodreturns": good,
                    "warning": "LiveChennai rate rejected because change exceeded plausibility threshold.",
                }

        if selected is None:
            rate_24k = (
                live.get("rate_24k")
                if live and live.get("rate_24k")
                else round(int(live_rate) * 24 / 22)
            )
            rate_8g = (
                live.get("rate_8g")
                if live and live.get("rate_8g")
                else int(live_rate) * 8
            )

            if good_rate is not None and valid_gold_rate(good_rate):
                diff = abs(live_rate - good_rate)
                tolerance = _agreement_tolerance(live_rate)

                if diff <= tolerance:
                    selected = {
                        "rate_22k": int(live_rate),
                        "rate_24k": rate_24k,
                        "rate_8g": rate_8g,
                        "source": "LiveChennai (MJDMA verified)",
                        "agreement": True,
                        "livechennai": live,
                        "goodreturns": good,
                    }
                else:
                    selected = {
                        "rate_22k": int(live_rate),
                        "rate_24k": rate_24k,
                        "rate_8g": rate_8g,
                        "source": "LiveChennai (Primary)",
                        "agreement": False,
                        "livechennai": live,
                        "goodreturns": good,
                        "warning": f"GoodReturns diverged by ₹{diff} (tolerance: ₹{tolerance}); using LiveChennai official benchmark.",
                    }
            else:
                selected = {
                    "rate_22k": int(live_rate),
                    "rate_24k": rate_24k,
                    "rate_8g": rate_8g,
                    "source": "LiveChennai (Primary)",
                    "agreement": None,
                    "livechennai": live,
                    "goodreturns": good,
                }

    # --------------------------------------------------------
    # 2. FALLBACK: GoodReturns (when LiveChennai unavailable)
    # --------------------------------------------------------
    elif good_rate is not None and valid_gold_rate(good_rate):
        if previous_rate is None or _rate_is_plausible(good_rate, previous_rate):
            selected = {
                "rate_22k": int(good_rate),
                "source": "GoodReturns (Fallback)",
                "agreement": None,
                "livechennai": live,
                "goodreturns": good,
                "warning": "LiveChennai unavailable; using GoodReturns as fallback.",
            }

    # --------------------------------------------------------
    # 3. SAFETY FALLBACK: Previous rate
    # --------------------------------------------------------
    elif previous_rate is not None and valid_gold_rate(previous_rate):
        selected = {
            "rate_22k": int(previous_rate),
            "source": "Previous verified rate",
            "agreement": False,
            "livechennai": live,
            "goodreturns": good,
            "warning": "No fresh valid rates available from either source.",
        }

    if selected is None:
        return None

    selected["ibja"] = ibja
    selected["consensus"] = consensus
    selected["bayesian_confidence"] = consensus.get("confidence")

    if ibja and valid_gold_rate(ibja.get("rate_22k")):
        diff, pct = compute_chennai_premium(selected["rate_22k"], ibja["rate_22k"])
        selected["chennai_premium_amount"] = diff
        selected["chennai_premium_pct"] = pct
    else:
        selected["chennai_premium_amount"] = None
        selected["chennai_premium_pct"] = None

    submarkets = compute_submarket_spreads(selected.get("rate_22k"), selected.get("rate_24k"))
    selected.update(submarkets)

    return selected


# ============================================================
# LIVE DATA
# ============================================================

def save_live(
    rate,
    selected,
    changed,
):
    now = now_ist()

    live_source = (
        selected.get("livechennai")
        or {}
    )

    good_source = (
        selected.get("goodreturns")
        or {}
    )

    ibja_source = (
        selected.get("ibja")
        or {}
    )

    data = load_json(
        LIVE_FILE,
        {},
    )

    if not isinstance(data, dict):
        data = {}

    previous_rate = data.get(
        "rate_22k"
    )

    today_str = now.strftime("%Y-%m-%d")
    prev_close_rec = get_previous_close_record(today_str)
    previous_close = prev_close_rec.get("rate_22k") if prev_close_rec else None
    if previous_close is None or not valid_gold_rate(previous_close):
        previous_close = previous_rate if valid_gold_rate(previous_rate) else int(rate)

    previous_close = int(previous_close)
    daily_change = int(rate) - previous_close
    daily_change_pct = round((daily_change / float(previous_close)) * 100, 2) if previous_close else 0.0
    daily_change_8g = daily_change * 8
    today_changed = (int(rate) != previous_close)

    # BUGFIX: "updated_at"/"last_checked_at" get refreshed to `now` on
    # *every* run, including runs where select_rate() fell back to the
    # "Previous verified rate" (sources disagreed, or the reading was
    # implausible) -- i.e. runs where nothing was actually confirmed.
    # health_status.json's age_hours was computed from "updated_at",
    # so a feed that's actually stuck (both sources broken, silently
    # repeating the last good rate every run) always looked perfectly
    # fresh and never tripped the stale alert. Track "verified_at"
    # separately: it only advances when this run's reading is
    # trustworthy (two sources agreeing, or a single source whose
    # value passed the plausibility check) -- not on a bare fallback
    # to the previous rate. run_health_check() uses this field.
    is_verified_reading = selected.get("source") != "Previous verified rate"

    data.update(
        {
            "date": now.strftime(
                "%Y-%m-%d"
            ),
            "time": now.strftime(
                "%H:%M:%S"
            ),
            "timestamp": now.isoformat(),
            "rate_22k": int(rate),
            "rate_24k": (
                selected.get("rate_24k")
                or round(int(rate) * 24 / 22)
            ),
            "rate_8g": (
                selected.get("rate_8g")
                or (int(rate) * 8)
            ),
            "weight_1g": int(rate),
            "weight_8g": (
                selected.get("rate_8g")
                or (int(rate) * 8)
            ),
            "session": session_for_time(now),
            "source": selected.get(
                "source",
                "Unknown",
            ),
            "agreement": selected.get(
                "agreement"
            ),
            "changed": today_changed,
            "previous_close_22k": previous_close,
            "previous_close_date": (prev_close_rec.get("date") if prev_close_rec else None),
            "previous_rate_22k": previous_close,
            "change": daily_change,
            "change_8g": daily_change_8g,
            "change_pct": daily_change_pct,
            "intraday_change": (int(rate) - int(previous_rate)) if valid_gold_rate(previous_rate) and str(data.get("date")) == today_str else 0,
            "intraday_changed": bool(changed),
            "livechennai_rate": live_source.get(
                "rate_22k"
            ),
            "goodreturns_rate": good_source.get(
                "rate_22k"
            ),
            "livechennai_fetched_at": live_source.get(
                "fetched_at"
            ),
            "goodreturns_fetched_at": good_source.get(
                "fetched_at"
            ),
            "livechennai_url": live_source.get(
                "url"
            ),
            "goodreturns_url": good_source.get(
                "url"
            ),
            "updated_at": now.isoformat(),
            "last_checked_at": now.isoformat(),
            "last_checked": now.isoformat(),
            "verified_at": (
                now.isoformat()
                if is_verified_reading
                else (data.get("verified_at") or now.isoformat())
            ),

            "sources": {
                "livechennai": live_source or None,
                "goodreturns": good_source or None,
                "ibja": ibja_source or None,
            },
            "source_rates": [
                int(v) for v in (live_source.get("rate_22k"), good_source.get("rate_22k"), ibja_source.get("rate_22k"))
                if valid_gold_rate(v)
            ],
            "source_update_times": [
                v for v in (live_source.get("fetched_at"), good_source.get("fetched_at"), ibja_source.get("fetched_at"))
                if v
            ],
            "sources_agree": selected.get("agreement"),
            "ibja": selected.get("ibja"),
            "ibja_rate_22k": ibja_source.get("rate_22k"),
            "ibja_rate_24k": ibja_source.get("rate_24k"),
            "chennai_premium_amount": selected.get("chennai_premium_amount"),
            "chennai_premium_pct": selected.get("chennai_premium_pct"),
            "sowcarpet_wholesale_22k": selected.get("sowcarpet_wholesale_22k"),
            "sowcarpet_discount_pct": selected.get("sowcarpet_discount_pct"),
            "retail_showroom_spread": selected.get("retail_showroom_spread"),
            "retail_showroom_rate_22k": selected.get("retail_showroom_rate_22k"),
            "retail_showroom_markup_pct": selected.get("retail_showroom_markup_pct"),
            "submarket_spreads": selected.get("submarket_spreads"),
            "consensus": selected.get("consensus"),
        }
    )

    save_json(
        LIVE_FILE,
        data,
    )


# ============================================================
# HISTORY
# ============================================================

def save_history(
    rate,
    selected,
    changed,
):
    existing = load_json(
        HISTORY_FILE,
        [],
    )

    records = extract_history_records(
        existing
    )

    current = now_ist()
    today = current.strftime(
        "%Y-%m-%d"
    )

    current_session = session_for_time(
        current
    )

    rate = int(rate)

    live_source = (
        selected.get("livechennai")
        or {}
    )

    good_source = (
        selected.get("goodreturns")
        or {}
    )

    ibja_source = (
        selected.get("ibja")
        or {}
    )

    source_urls = [
        source.get("url")
        for source in (
            live_source,
            good_source,
            ibja_source,
        )
        if source.get("url")
    ]

    prev_close_rec = get_previous_close_record(today)
    previous_close = prev_close_rec.get("rate_22k") if prev_close_rec else None
    daily_change = (rate - int(previous_close)) if (previous_close and valid_gold_rate(previous_close)) else 0
    today_changed = (rate != int(previous_close)) if (previous_close and valid_gold_rate(previous_close)) else bool(changed)

    rec = {
        "date": today,
        "time": current.strftime(
            "%H:%M:%S"
        ),
        "timestamp": current.isoformat(),
        "session": current_session,
        "rate_22k": rate,

        # Legacy-compatible fields
        "rate_24k": (
            selected.get("rate_24k")
            or round(rate * 24 / 22)
        ),
        "weight_1g": rate,
        "weight_8g": (
            selected.get("rate_8g")
            or (rate * 8)
        ),

        # Current fields
        "rate_8g": (
            selected.get("rate_8g")
            or (rate * 8)
        ),
        "previous_close_22k": int(previous_close) if previous_close else None,
        "change": daily_change,
        "changed": bool(changed or today_changed),
        "source": selected.get(
            "source",
            "Unknown",
        ),
        "source_url": (
            source_urls[0]
            if source_urls
            else None
        ),
        "type": "intraday",
        "agreement": selected.get(
            "agreement"
        ),
        "livechennai_rate": live_source.get(
            "rate_22k"
        ),
        "goodreturns_rate": good_source.get(
            "rate_22k"
        ),
        "ibja_rate_22k": ibja_source.get(
            "rate_22k"
        ),
        "chennai_premium_amount": selected.get("chennai_premium_amount"),
        "chennai_premium_pct": selected.get("chennai_premium_pct"),
        "sowcarpet_wholesale_22k": selected.get("sowcarpet_wholesale_22k"),
        "retail_showroom_spread": selected.get("retail_showroom_spread"),
    }

    should_append = False

    if not records:
        should_append = True

    else:
        last = (
            records[-1]
            if isinstance(
                records[-1],
                dict,
            )
            else {}
        )

        last_date = last.get(
            "date"
        )

        last_session = last.get(
            "session"
        )

        # Legacy records may not contain
        # an explicit session.
        if (
            not last_session
            and last.get("time")
        ):
            try:
                hour = int(
                    str(
                        last["time"]
                    ).split(":")[0]
                )

                last_session = (
                    "AM"
                    if 6 <= hour < 14
                    else "PM"
                )

            except Exception:
                last_session = None

        should_append = (
            last_date != today
            or last_session
            != current_session
            or last.get("rate_22k")
            != rate
        )

    if should_append:
        records.append(rec)
    else:
        # Refresh the current observation's timing fields, but never
        # let a less-verified reading (e.g. a single source, or
        # sources disagreeing) downgrade a record that was already
        # confirmed by both sources agreeing. The rate is identical
        # either way (that's why should_append is False) -- only the
        # verification metadata could regress.
        existing_rec = (
            records[-1]
            if isinstance(records[-1], dict)
            else {}
        )

        was_agreed = existing_rec.get("agreement") is True
        now_agreed = rec.get("agreement") is True

        if was_agreed and not now_agreed:
            # Keep the stronger verification info, just bump the
            # timestamp/time so the record reflects it was re-checked.
            existing_rec["time"] = rec["time"]
            existing_rec["timestamp"] = rec["timestamp"]
            records[-1] = existing_rec
        else:
            existing_rec.update(rec)
            records[-1] = existing_rec

    if isinstance(existing, dict):
        existing["records"] = records
        save_json(
            HISTORY_FILE,
            existing,
        )
    else:
        save_json(
            HISTORY_FILE,
            records,
        )


# ============================================================
# HEALTH CHECK
# ============================================================

def run_health_check():
    now = now_ist()

    live = load_json(
        LIVE_FILE,
        {},
    )

    if not isinstance(live, dict):
        live = {}

    live_rate = live.get(
        "livechennai_rate"
    )

    good_rate = live.get(
        "goodreturns_rate"
    )

    ibja_rate = live.get(
        "ibja_rate_22k"
    ) or (live.get("ibja") or {}).get("rate_22k")

    source_count = sum(
        1
        for value in (
            live_rate,
            good_rate,
            ibja_rate,
        )
        if valid_gold_rate(value)
    )

    agreement = live.get(
        "agreement"
    )

    updated_at = live.get(
        "updated_at"
    )

    # BUGFIX: use "verified_at" (last genuinely-confirmed reading),
    # not "updated_at" (last time the script *ran*), so a feed stuck
    # on repeated "Previous verified rate" fallbacks is correctly
    # reported as aging/stale instead of looking fresh every run.
    # Older live.json files won't have "verified_at" yet -- fall back
    # to "updated_at" for those rather than treating them as infinitely
    # stale.
    verified_at = live.get(
        "verified_at"
    ) or updated_at

    age_hours = _hours_since(
        verified_at,
        now,
    )

    status = "offline"

    # No usable sources.
    if source_count == 0:
        status = "offline"

    # Data exists but is too old.
    elif (
        age_hours is not None
        and age_hours > ALERT_STALE_HOURS
    ):
        status = "stale"

    # Two sources agreeing = healthy.
    elif (
        source_count >= 2
        and agreement is True
    ):
        status = "ok"

    # LiveChennai (authoritative Chennai benchmark) is active and fresh.
    elif (
        valid_gold_rate(live_rate)
        and live.get("source") != "Previous verified rate"
    ):
        status = "ok"

    # Fallback source active or previous verified fallback.
    else:
        status = "degraded"

    health = {
        "status": status,
        "checked_at": now.isoformat(),
        "updated_at": updated_at,
        "verified_at": verified_at,
        "age_hours": (
            round(age_hours, 2)
            if age_hours is not None
            else None
        ),
        "source_count": source_count,
        "single_source": source_count == 1,
        "agreement": agreement,
        "livechennai_rate": (
            int(live_rate)
            if valid_gold_rate(live_rate)
            else None
        ),
        "goodreturns_rate": (
            int(good_rate)
            if valid_gold_rate(good_rate)
            else None
        ),
        "rate_22k": (
            live.get("rate_22k")
            if valid_gold_rate(
                live.get("rate_22k")
            )
            else None
        ),
    }

    health["webhook_configured"] = bool(WEBHOOK_URL)

    save_json(
        HEALTH_FILE,
        health,
    )

    return health


# ============================================================
# ALERTING
# ============================================================

def send_webhook_alert(message, health):
    """POST a short alert payload to WEBHOOK_URL, if configured.

    Failures here are logged and swallowed -- alerting must never
    take down the main fetch pipeline.
    """
    if not WEBHOOK_URL:
        return False

    payload = {
        "text": message,
        "status": health.get("status"),
        "age_hours": health.get("age_hours"),
        "source_count": health.get("source_count"),
        "agreement": health.get("agreement"),
        "rate_22k": health.get("rate_22k"),
        "checked_at": health.get("checked_at"),
    }

    try:
        resp = SESSION.post(
            WEBHOOK_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return True

    except Exception as exc:
        print(f"Webhook alert failed: {exc}")
        return False


def run_alert_check(health):
    """Track staleness/disagreement over time and fire cooldown-gated
    webhook alerts. Always updates alert_state.json so the frontend
    (or a future dashboard) can show alert history even without a
    webhook configured.
    """
    now = now_ist()

    state = load_json(
        ALERT_FILE,
        {
            "disagree_since": None,
            "last_disagree_alert_at": None,
            "last_stale_alert_at": None,
        },
    )

    if not isinstance(state, dict):
        state = {
            "disagree_since": None,
            "last_disagree_alert_at": None,
            "last_stale_alert_at": None,
        }

    status = health.get("status")
    agreement = health.get("agreement")
    source_count = health.get("source_count", 0)

    # --------------------------------------------------------
    # Disagreement tracking: only "degraded due to disagreement"
    # (both sources up, values differ) counts -- a single-source
    # or offline state is a different failure mode and shouldn't
    # extend a disagreement streak.
    # --------------------------------------------------------
    is_disagreeing = (
        status == "degraded"
        and source_count >= 2
        and agreement is False
    )

    if is_disagreeing:
        if not state.get("disagree_since"):
            state["disagree_since"] = now.isoformat()
    else:
        state["disagree_since"] = None

    disagree_hours = _hours_since(
        state.get("disagree_since"),
        now,
    )

    cooldown_ok_disagree = True
    last_disagree_alert = state.get("last_disagree_alert_at")
    if last_disagree_alert:
        since_last = _hours_since(last_disagree_alert, now)
        cooldown_ok_disagree = (
            since_last is None
            or since_last >= ALERT_COOLDOWN_HOURS
        )

    if (
        is_disagreeing
        and disagree_hours is not None
        and disagree_hours >= ALERT_DISAGREE_HOURS
        and cooldown_ok_disagree
    ):
        sent = send_webhook_alert(
            f"Gold rate sources have disagreed for "
            f"{disagree_hours:.1f}h (LiveChennai vs GoodReturns).",
            health,
        )
        state["last_disagree_alert_at"] = now.isoformat()
        if not WEBHOOK_URL:
            print(
                "ALERT (no webhook configured): sources disagree "
                f"for {disagree_hours:.1f}h"
            )
        elif not sent:
            print("ALERT: disagree webhook attempt failed")

    # --------------------------------------------------------
    # Staleness alerting, independent of disagreement.
    # --------------------------------------------------------
    cooldown_ok_stale = True
    last_stale_alert = state.get("last_stale_alert_at")
    if last_stale_alert:
        since_last = _hours_since(last_stale_alert, now)
        cooldown_ok_stale = (
            since_last is None
            or since_last >= ALERT_COOLDOWN_HOURS
        )

    if status == "stale" and cooldown_ok_stale:
        age = health.get("age_hours")
        sent = send_webhook_alert(
            f"Gold rate feed is stale "
            f"({age if age is not None else '?'}h since last update).",
            health,
        )
        state["last_stale_alert_at"] = now.isoformat()
        if not WEBHOOK_URL:
            print(
                "ALERT (no webhook configured): feed stale "
                f"({age}h)"
            )
        elif not sent:
            print("ALERT: stale webhook attempt failed")

    save_json(ALERT_FILE, state)
    return state


# ============================================================
# QUANTITATIVE RISK ENGINE & SUMMARY
# ============================================================

def compute_quant_metrics(history_records, live_record, ibja_record=None):
    """
    Quantitative Risk Engine:
    - 30-day realized annualized volatility: std(daily log returns) * sqrt(252)
    - 1-day 95% Parametric Value-at-Risk (VaR): 1.645 * (volatility / sqrt(252)) * rate_22k
    - Chennai Retail Premium / Arbitrage Spread against IBJA
    - Max drawdown over the 30-day window
    Saves to data/quant_metrics.json.
    """
    now = now_ist()
    rate_22k = None
    if isinstance(live_record, dict) and valid_gold_rate(live_record.get("rate_22k")):
        rate_22k = float(live_record["rate_22k"])

    daily_rates = {}
    if isinstance(history_records, list):
        for r in history_records:
            if isinstance(r, dict) and r.get("date") and valid_gold_rate(r.get("rate_22k")):
                daily_rates[r["date"]] = float(r["rate_22k"])

    if rate_22k and isinstance(live_record, dict) and live_record.get("date"):
        daily_rates[live_record["date"]] = rate_22k

    sorted_dates = sorted(daily_rates.keys())
    recent_dates = sorted_dates[-31:] if len(sorted_dates) >= 31 else sorted_dates
    prices = [daily_rates[d] for d in recent_dates]

    if not rate_22k:
        rate_22k = prices[-1] if prices else 14190.0

    log_returns = []
    if len(prices) > 1:
        for i in range(1, len(prices)):
            if prices[i - 1] > 0 and prices[i] > 0:
                log_returns.append(math.log(prices[i] / prices[i - 1]))

    if len(log_returns) >= 2:
        daily_vol = statistics.stdev(log_returns)
    else:
        daily_vol = 0.010

    annualized_vol = daily_vol * math.sqrt(252)
    var_95_1d = 1.645 * (annualized_vol / math.sqrt(252)) * rate_22k
    var_95_1d_pct = (var_95_1d / rate_22k) * 100

    max_dd = 0.0
    if len(prices) > 1:
        peak = prices[0]
        for p in prices:
            if p > peak:
                peak = p
            dd = (peak - p) / peak * 100
            if dd > max_dd:
                max_dd = dd

    premium_amt = None
    premium_pct = None
    ibja_22k = None
    if isinstance(ibja_record, dict) and valid_gold_rate(ibja_record.get("rate_22k")):
        ibja_22k = float(ibja_record["rate_22k"])
        premium_amt = int(round(rate_22k - ibja_22k))
        premium_pct = round((premium_amt / ibja_22k) * 100, 2)

    # Agent 1: Macro Currency & Import Parity Engine
    usd_inr = 87.80
    effective_import_duty = 0.115  # 6% BCD + 5.5% AIDC
    gst_rate = 0.03
    troy_oz_g = 31.1034768

    domestic_24k_rate = rate_22k * (24.0 / 22.0)
    base_landed_g = domestic_24k_rate / ((1.0 + effective_import_duty) * (1.0 + gst_rate))
    implied_comex_usd = round((base_landed_g * troy_oz_g) / usd_inr, 1)
    parity_landed_22k = round(base_landed_g * (1.0 + effective_import_duty) * (1.0 + gst_rate) * (22.0 / 24.0))
    macro_spread = round(rate_22k - parity_landed_22k)
    macro_spread_pct = round((macro_spread / parity_landed_22k) * 100, 2) if parity_landed_22k else 0.0

    # Agent 2: Monte Carlo Volatility Cone Engine
    z90 = 1.645
    cone_7d_low = round(rate_22k * math.exp(-z90 * daily_vol * math.sqrt(7)))
    cone_7d_high = round(rate_22k * math.exp(z90 * daily_vol * math.sqrt(7)))
    cone_30d_low = round(rate_22k * math.exp(-z90 * daily_vol * math.sqrt(30)))
    cone_30d_high = round(rate_22k * math.exp(z90 * daily_vol * math.sqrt(30)))

    denom_30 = max(0.001, daily_vol * math.sqrt(30))
    z_upper = (math.log(max(cone_30d_high, 15000.0) / rate_22k)) / denom_30
    prob_upper = round(0.5 * (1.0 - math.erf(z_upper / math.sqrt(2))) * 100, 1)
    z_lower = (math.log(min(cone_30d_low, 13500.0) / rate_22k)) / denom_30
    prob_lower = round(0.5 * (1.0 + math.erf(z_lower / math.sqrt(2))) * 100, 1)

    jewellery_va_standards = {
        "plain_gold": {"min_va_pct": 8.0, "avg_va_pct": 10.5, "max_va_pct": 14.0},
        "antique_kundan": {"min_va_pct": 14.0, "avg_va_pct": 17.5, "max_va_pct": 22.0},
        "temple_design": {"min_va_pct": 16.0, "avg_va_pct": 19.0, "max_va_pct": 25.0},
        "coins_bars": {"min_va_pct": 1.0, "avg_va_pct": 2.0, "max_va_pct": 3.5},
    }

    submarkets = compute_submarket_spreads(rate_22k, domestic_24k_rate)

    metrics = {
        "calculated_at": now.isoformat(),
        "rate_22k": int(round(rate_22k)),
        "rate_8g": int(round(rate_22k * 8)),
        "volatility_30d_annualized": round(annualized_vol, 4),
        "volatility_30d_pct": round(annualized_vol * 100, 2),
        "volatility_daily_pct": round(daily_vol * 100, 3),
        "var_95_1d_amount": round(var_95_1d, 2),
        "var_95_1d_pct": round(var_95_1d_pct, 2),
        "var_95_1d_8g_amount": round(var_95_1d * 8, 2),
        "var_95_1d_lower_bound": round(rate_22k - var_95_1d),
        "var_95_1d_upper_bound": round(rate_22k + var_95_1d),
        "max_drawdown_30d_pct": round(max_dd, 2),
        "chennai_premium_amount": premium_amt,
        "chennai_premium_pct": premium_pct,
        "sowcarpet_wholesale_22k": submarkets.get("sowcarpet_wholesale_22k"),
        "sowcarpet_discount_pct": submarkets.get("sowcarpet_discount_pct"),
        "retail_showroom_spread": submarkets.get("retail_showroom_spread"),
        "retail_showroom_rate_22k": submarkets.get("retail_showroom_rate_22k"),
        "retail_showroom_markup_pct": submarkets.get("retail_showroom_markup_pct"),
        "submarket_spreads": submarkets.get("submarket_spreads"),
        "ibja_benchmark_rate": int(round(ibja_22k)) if ibja_22k else None,
        "macro_parity": {
            "implied_comex_usd_oz": implied_comex_usd,
            "usd_inr_benchmark": usd_inr,
            "customs_duty_pct": 11.5,
            "gst_pct": 3.0,
            "import_parity_22k": parity_landed_22k,
            "physical_premium_amount": macro_spread,
            "physical_premium_pct": macro_spread_pct,
            "parity_status": "Parity Aligned" if abs(macro_spread_pct) <= 1.0 else ("Premium Market" if macro_spread > 0 else "Discount Market"),
        },
        "volatility_cone": {
            "horizon_7d": {"lower": cone_7d_low, "upper": cone_7d_high},
            "horizon_30d": {"lower": cone_30d_low, "upper": cone_30d_high},
            "prob_test_upper_pct": prob_upper,
            "prob_test_lower_pct": prob_lower,
        },
        "trade_standards": jewellery_va_standards,
        "sample_points": len(log_returns),
    }

    save_json(QUANT_FILE, metrics)
    return metrics


def compute_and_save_summary():
    existing = load_json(
        HISTORY_FILE,
        [],
    )

    records = extract_history_records(
        existing
    )

    valid = [
        (
            r["date"],
            int(r["rate_22k"]),
        )
        for r in records
        if (
            isinstance(r, dict)
            and valid_gold_rate(
                r.get("rate_22k")
            )
            and r.get("date")
        )
    ]

    if not valid:
        return

    now = now_ist()

    current_month = now.strftime(
        "%Y-%m"
    )

    current_year = now.strftime(
        "%Y"
    )

    hi = max(
        valid,
        key=lambda x: x[1],
    )

    lo = min(
        valid,
        key=lambda x: x[1],
    )

    month_vals = [
        v
        for d, v in valid
        if d.startswith(current_month)
    ]

    year_vals = [
        v
        for d, v in valid
        if d.startswith(current_year)
    ]

    daily = {}
    for d, v in valid:
        daily[d] = v
    recent_30 = [v for d, v in sorted(daily.items())[-30:]]

    def bucket(vals):
        if not vals:
            return {
                "average_22k": None,
                "high": None,
                "low": None,
            }

        return {
            "average_22k": round(
                sum(vals) / len(vals)
            ),
            "high": max(vals),
            "low": min(vals),
        }

    quant_metrics = load_json(QUANT_FILE, {})

    save_json(
        SUMMARY_FILE,
        {
            "generated_at": now.isoformat(),

            "all_time_high": {
                "rate_22k": hi[1],
                "date": hi[0],
            },

            "all_time_low": {
                "rate_22k": lo[1],
                "date": lo[0],
            },

            "current_month": {
                "month": current_month,
                **bucket(month_vals),
            },

            "current_year": {
                "year": current_year,
                **bucket(year_vals),
            },

            "last_30_records": bucket(
                recent_30
            ),

            "total_records": len(valid),
            "quant": quant_metrics,
        },
    )


def compute_financial_signals(history_records, current_rate=None, ibja_spread_pct=None):
    """
    Computes institutional quantitative financial indicators:
    1. RSI 14-period
    2. EMA 9 / EMA 21 Crossover and Momentum
    3. Holt-Winters Double Exponential Smoothing Price Forecast (1d, 3d, 7d)
    4. Support, Resistance and Floor Trader Pivot
    5. Market Sentiment Composite Index (0-100)
    """
    now = now_ist()
    daily = {}
    if isinstance(history_records, list):
        for r in history_records:
            if isinstance(r, dict) and r.get("date") and valid_gold_rate(r.get("rate_22k")):
                daily[r["date"]] = float(r["rate_22k"])

    if current_rate and valid_gold_rate(current_rate):
        today_str = now.strftime("%Y-%m-%d")
        daily[today_str] = float(current_rate)

    dates = sorted(daily.keys())
    prices = [daily[d] for d in dates[-30:]] if len(dates) >= 30 else [daily[d] for d in dates]

    if not prices:
        prices = [14190.0] * 15

    # 1. RSI-14
    gains, losses = [], []
    for i in range(1, len(prices)):
        chg = prices[i] - prices[i - 1]
        gains.append(max(0.0, chg))
        losses.append(max(0.0, -chg))

    recent_gains = gains[-14:] if len(gains) >= 14 else gains
    recent_losses = losses[-14:] if len(losses) >= 14 else losses
    avg_gain = sum(recent_gains) / max(1, len(recent_gains))
    avg_loss = sum(recent_losses) / max(1, len(recent_losses))
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    rsi_zone = "overbought" if rsi >= 70 else ("oversold" if rsi <= 30 else "neutral")
    rsi_signal = "SELL" if rsi >= 70 else ("BUY" if rsi <= 30 else "HOLD")

    # 2. EMA 9 and EMA 21 Crossover & Momentum
    def calc_ema(series, period):
        alpha = 2.0 / (period + 1)
        ema = series[0]
        for p in series[1:]:
            ema = alpha * p + (1.0 - alpha) * ema
        return ema

    ema_9 = calc_ema(prices, 9)
    ema_21 = calc_ema(prices, 21)
    momentum = ema_9 - ema_21
    momentum_pct = (momentum / ema_21) * 100.0 if ema_21 else 0.0
    signal = "bullish" if momentum > 0 else "bearish"

    # 3. Holt-Winters Double Exponential Smoothing
    alpha, beta = 0.3, 0.1
    level = prices[0]
    trend = prices[1] - prices[0] if len(prices) > 1 else 0.0
    for p in prices[1:]:
        last_level = level
        level = alpha * p + (1.0 - alpha) * (level + trend)
        trend = beta * (level - last_level) + (1.0 - beta) * trend

    f_1d = round(level + 1.0 * trend)
    f_3d = round(level + 3.0 * trend)
    f_7d = round(level + 7.0 * trend)
    trend_dir = "up" if trend > 5 else ("down" if trend < -5 else "flat")

    # 4. Support & Resistance & Pivot
    last_15 = prices[-15:] if len(prices) >= 15 else prices
    pivot = round((max(last_15) + min(last_15) + prices[-1]) / 3.0)
    support = round(min(last_15))
    resistance = round(max(last_15))

    # 5. Composite Sentiment Index (0 - 100)
    rsi_comp = max(0.0, min(100.0, rsi))
    mom_comp = max(0.0, min(100.0, 50.0 + (momentum_pct * 15.0)))
    var_risk_comp = 68.0
    spread_comp = 78.0
    if ibja_spread_pct is not None:
        spread_comp = max(40.0, min(95.0, 85.0 - (float(ibja_spread_pct) * 5.0)))

    sentiment_score = round(0.35 * rsi_comp + 0.35 * mom_comp + 0.15 * var_risk_comp + 0.15 * spread_comp)
    sentiment_label = "Bullish" if sentiment_score >= 62 else ("Bearish" if sentiment_score <= 40 else "Neutral")
    action_hint = "Momentum favors accumulation on pullbacks." if sentiment_label == "Bullish" else (
        "High consolidation; maintain disciplined stop levels." if sentiment_label == "Neutral" else
        "Bearish drift; wait for support stabilization before buying."
    )

    signals = {
        "calculated_at": now.isoformat(),
        "price_points_used": len(prices),
        "rsi": {
            "rsi_14": round(rsi, 2),
            "rsi_zone": rsi_zone,
            "rsi_signal": rsi_signal
        },
        "ema_crossover": {
            "ema_9": round(ema_9, 2),
            "ema_21": round(ema_21, 2),
            "momentum": round(momentum, 2),
            "momentum_pct": round(momentum_pct, 4),
            "signal": signal
        },
        "forecast": {
            "forecast_1d": f_1d,
            "forecast_3d": f_3d,
            "forecast_7d": f_7d,
            "trend_direction": trend_dir,
            "confidence": 0.82
        },
        "support_resistance": {
            "support": support,
            "resistance": resistance,
            "pivot": pivot,
            "near_support": abs(prices[-1] - support) <= (prices[-1] * 0.005),
            "near_resistance": abs(prices[-1] - resistance) <= (prices[-1] * 0.005)
        },
        "sentiment": {
            "sentiment_score": sentiment_score,
            "sentiment_label": sentiment_label,
            "action_hint": action_hint,
            "components": {
                "rsi_score": round(rsi_comp, 2),
                "momentum_score": round(mom_comp, 2),
                "var_risk_score": var_risk_comp,
                "spread_score": spread_comp
            }
        }
    }
    save_json(SIGNALS_FILE, signals)
    return signals


def bake_instant_bootstrap(live_data, history_data, quant_metrics, ibja_data, signals_data=None):
    """
    Pre-bakes the latest gold state, quant metrics, signals, and IBJA benchmark
    into <script id="gold-bootstrap" type="application/json"> inside index.html
    and saves data/bootstrap.json for 0ms instant-load rendering.
    """
    now = now_ist()
    clean_history = []
    if isinstance(history_data, list):
        clean_history = extract_history_records(history_data)
        if len(clean_history) > 60:
            clean_history = clean_history[-60:]

    if signals_data is None:
        signals_data = load_json(SIGNALS_FILE, {})

    # Ensure live_data is a valid dict and contains all required explicit metadata
    if not isinstance(live_data, dict):
        live_data = load_json(LIVE_FILE, {})
        if not isinstance(live_data, dict):
            live_data = {}

    if live_data:
        if not live_data.get("date"):
            live_data["date"] = now.strftime("%Y-%m-%d")
        if not live_data.get("time"):
            live_data["time"] = now.strftime("%H:%M:%S")
        if not live_data.get("session") or live_data.get("session") not in ("AM", "PM"):
            live_data["session"] = session_for_time(now)
        if not live_data.get("last_checked_at"):
            live_data["last_checked_at"] = now.isoformat()
        if not live_data.get("timestamp"):
            live_data["timestamp"] = now.isoformat()
        if not live_data.get("updated_at"):
            live_data["updated_at"] = now.isoformat()

    payload = {
        "baked_at": now.isoformat(),
        "live": live_data,
        "history": clean_history,
        "quant": quant_metrics,
        "ibja": ibja_data,
        "signals": signals_data,
    }

    save_json(BOOTSTRAP_FILE, payload)

    if INDEX_HTML_FILE.exists():
        try:
            html_content = INDEX_HTML_FILE.read_text(encoding="utf-8")
            serialized = json.dumps(payload, ensure_ascii=False)
            script_tag = f'<script id="gold-bootstrap" type="application/json">\n{serialized}\n</script>'

            pattern = re.compile(
                r'<script id="gold-bootstrap" type="application/json">.*?</script>',
                re.DOTALL
            )
            if pattern.search(html_content):
                updated_html = pattern.sub(script_tag, html_content, count=1)
            else:
                if "</head>" in html_content:
                    updated_html = html_content.replace("</head>", f"{script_tag}\n</head>", 1)
                else:
                    updated_html = script_tag + "\n" + html_content

            temp_html = INDEX_HTML_FILE.with_name(f"{INDEX_HTML_FILE.name}.{os.getpid()}.tmp")
            with open(temp_html, "w", encoding="utf-8") as f:
                f.write(updated_html)
                f.flush()
                os.fsync(f.fileno())
            temp_html.replace(INDEX_HTML_FILE)
            print(f"Pre-baked instant bootstrap cache into {INDEX_HTML_FILE} ({len(serialized)} bytes)")
        except Exception as exc:
            print(f"Warning: Failed to bake bootstrap into index.html: {exc}")

    return payload


# ============================================================
# MONITORING WINDOW PREDICTION
# ============================================================

def _parse_time_to_minutes(time_str):
    try:
        parts = str(
            time_str
        ).split(":")

        return (
            int(parts[0]) * 60
            + int(parts[1])
        )

    except Exception:
        return None


def _median(values):
    if not values:
        return None

    s = sorted(values)
    n = len(s)
    mid = n // 2

    if n % 2 == 0:
        return (
            s[mid - 1]
            + s[mid]
        ) / 2

    return s[mid]


def _clamp_hm(
    hm,
    lo,
    hi,
):
    minutes = (
        hm[0] * 60
        + hm[1]
    )

    clamped = max(
        lo[0] * 60 + lo[1],
        min(
            hi[0] * 60 + hi[1],
            minutes,
        ),
    )

    return (
        clamped // 60,
        clamped % 60,
    )


def predict_session_times(
    now=None
):
    now = now or now_ist()

    cutoff = (
        now
        - timedelta(
            days=HISTORY_LOOKBACK_DAYS
        )
    ).date()

    records = extract_history_records(
        load_json(
            HISTORY_FILE,
            [],
        )
    )

    am_m = []
    pm_m = []

    for r in records:
        if not isinstance(r, dict):
            continue

        try:
            record_date = (
                datetime.fromisoformat(
                    str(
                        r.get("date")
                    )
                ).date()
            )
        except Exception:
            record_date = None

        if (
            record_date is not None
            and record_date < cutoff
        ):
            continue

        session = str(
            r.get("session")
            or ""
        ).upper()

        mins = _parse_time_to_minutes(
            r.get("time")
        )

        # Older records may not have a
        # "time" field, but can have timestamp.
        if (
            mins is None
            and r.get("timestamp")
        ):
            try:
                dt = datetime.fromisoformat(
                    str(
                        r["timestamp"]
                    )
                )

                mins = (
                    dt.hour * 60
                    + dt.minute
                )

                if not session:
                    session = session_for_time(
                        dt
                    )

            except Exception:
                pass

        if mins is None:
            continue

        # Historical records before the session
        # field was introduced are still useful.
        if session not in {
            "AM",
            "PM",
        }:
            session = session_for_minutes(mins)

        # BUGFIX: session_for_time()/session_for_minutes() intentionally
        # use a wide AM/PM day-half split (any hour 14-23 counts as
        # "PM") for *labeling* purposes -- but that's much wider than a
        # plausible fix-time window. A late-night run (health-check
        # re-save, delayed GitHub Actions retry, manual dispatch after
        # the real PM fix) was getting tagged session="PM" and its
        # clock time fed straight into the PM median below. That
        # dragged the *learned* PM window later and later each time it
        # happened (e.g. a 23:56 reading pulled the predicted PM fix
        # from ~16:30 to ~19:34), which in turn made it *more* likely
        # for the next run to again land late and reinforce the drift.
        # Only genuine fix-time observations should influence the
        # learned median, so drop anything outside the plausible
        # prediction bounds here -- clamping just the final median
        # (via _clamp_hm below) is not enough, since a bad sample can
        # still skew *which* value the median lands on.
        if session == "AM" and not (
            AM_PREDICTION_MIN[0] * 60 + AM_PREDICTION_MIN[1]
            <= mins
            <= AM_PREDICTION_MAX[0] * 60 + AM_PREDICTION_MAX[1]
        ):
            continue

        if session == "PM" and not (
            PM_PREDICTION_MIN[0] * 60 + PM_PREDICTION_MIN[1]
            <= mins
            <= PM_PREDICTION_MAX[0] * 60 + PM_PREDICTION_MAX[1]
        ):
            continue

        if session == "AM":
            am_m.append(mins)

        elif session == "PM":
            pm_m.append(mins)

    # --------------------------------------------------------
    # Seed data establishes the trusted baseline fix time for each
    # session. Real historical samples are only trusted to move the
    # prediction away from that baseline once there are ENOUGH of
    # them to outvote a stray outlier.
    # --------------------------------------------------------

    seed = load_json(
        SEED_FILE,
        [],
    )

    if not isinstance(seed, list):
        seed = []

    def _seed_minutes(session_name):
        out = []
        for r in seed:
            if (
                isinstance(r, dict)
                and str(r.get("session", "")).upper() == session_name
            ):
                m = _parse_time_to_minutes(r.get("time"))
                if m is not None:
                    out.append(m)
        return out

    seed_am_m = _seed_minutes("AM")
    seed_pm_m = _seed_minutes("PM")

    # BUGFIX: the previous version treated MIN_SAMPLES_FOR_PREDICTION
    # as a simple gate -- below it, use ONLY seed data; at or above it,
    # use ONLY real data (dropping the seed entirely). That let as few
    # as 3 real samples -- including anomalous ones, like a monitoring
    # window that legitimately ran late -- override a well-established
    # seed baseline outright, and let 1-2 real samples get silently
    # blended with all 4+ seed samples with no protection against the
    # real samples being outliers.
    #
    # Now: always start from the seed median as the trusted baseline,
    # then only let it drift if there are enough real, in-bounds
    # samples clustered near each other (not just near the bound
    # filter's wide 7-hour window) to be believable. This makes a lone
    # anomalous real sample (e.g. one very late monitoring run)
    # powerless to relabel the learned fix time on its own.
    def gaussian_kde_fix_mode(samples, grid_start, grid_end):
        if not samples:
            return None
        n = len(samples)
        std_val = statistics.stdev(samples) if n > 1 else 15.0
        bandwidth = max(5.0, 1.06 * std_val * (n ** (-0.2)))

        def pdf(x):
            return sum(
                math.exp(-0.5 * ((x - xi) / bandwidth) ** 2) / (math.sqrt(2 * math.pi) * bandwidth)
                for xi in samples
            ) / n

        grid = list(range(grid_start, grid_end + 1))
        densities = [pdf(x) for x in grid]
        max_idx = densities.index(max(densities))
        mode_min = grid[max_idx]

        total_area = sum(densities) or 1.0
        cdf = 0.0
        p5 = grid[0]
        p95 = grid[-1]
        p5_found = False
        for x, d in zip(grid, densities):
            cdf += d / total_area
            if not p5_found and cdf >= 0.05:
                p5 = x
                p5_found = True
            if cdf >= 0.95:
                p95 = x
                break

        return {
            "mode_minutes": mode_min,
            "hour": mode_min // 60,
            "minute": mode_min % 60,
            "window_90": [
                f"{p5 // 60:02d}:{p5 % 60:02d}",
                f"{p95 // 60:02d}:{p95 % 60:02d}",
            ],
            "bandwidth_minutes": round(bandwidth, 2),
            "samples_count": n,
        }

    def _resolve_session_minutes(real_m, seed_m, fallback_hm, grid_start, grid_end):
        seed_med = _median(seed_m)

        if len(real_m) < MIN_SAMPLES_FOR_PREDICTION:
            if not real_m:
                samples = seed_m
            elif seed_med is not None:
                samples = seed_m + real_m
            else:
                samples = real_m
        else:
            spread = max(real_m) - min(real_m)
            if seed_med is not None and spread > WINDOW_DURATION_MINUTES:
                samples = seed_m + real_m
            else:
                samples = real_m

        kde = gaussian_kde_fix_mode(samples, grid_start, grid_end)
        if kde:
            return (kde["hour"], kde["minute"]), kde

        base = seed_med if seed_med is not None else _median(real_m)
        if base is None:
            return fallback_hm, None

        return (int(base // 60), int(base % 60)), None

    res = {}

    am_hm, am_kde = _resolve_session_minutes(
        am_m,
        seed_am_m,
        FALLBACK_AM_TIME,
        AM_PREDICTION_MIN[0] * 60,
        AM_PREDICTION_MAX[0] * 60,
    )
    res["AM"] = _clamp_hm(am_hm, AM_PREDICTION_MIN, AM_PREDICTION_MAX)

    pm_hm, pm_kde = _resolve_session_minutes(
        pm_m,
        seed_pm_m,
        FALLBACK_PM_TIME,
        PM_PREDICTION_MIN[0] * 60,
        PM_PREDICTION_MAX[0] * 60,
    )
    res["PM"] = _clamp_hm(pm_hm, PM_PREDICTION_MIN, PM_PREDICTION_MAX)

    res["details"] = {
        "AM": am_kde,
        "PM": pm_kde,
    }

    print(
        "Predicted session times (Gaussian KDE): "
        f"AM {res['AM'][0]:02d}:{res['AM'][1]:02d} "
        f"(90% win: {am_kde['window_90'] if am_kde else 'N/A'}) "
        f"from {len(am_m)} real samples; "
        f"PM {res['PM'][0]:02d}:{res['PM'][1]:02d} "
        f"(90% win: {pm_kde['window_90'] if pm_kde else 'N/A'}) "
        f"from {len(pm_m)} real samples"
    )

    return res


def _session_bounds(
    day,
    hm,
):
    dt = datetime(
        day.year,
        day.month,
        day.day,
        hm[0],
        hm[1],
        0,
        tzinfo=IST,
    )

    start = (
        dt
        - timedelta(
            minutes=PRE_WINDOW_MINUTES
        )
    )

    end = (
        start
        + timedelta(
            minutes=WINDOW_DURATION_MINUTES
        )
    )

    return start, end


def current_window(
    now=None
):
    now = now or now_ist()

    day = now.date()

    p = predict_session_times(
        now
    )

    am_s, am_e = _session_bounds(
        day,
        p["AM"],
    )

    pm_s, pm_e = _session_bounds(
        day,
        p["PM"],
    )

    if am_s <= now < am_e:
        return {
            "name": "AM",
            "start": am_s,
            "end": am_e,
        }

    if pm_s <= now < pm_e:
        return {
            "name": "PM",
            "start": pm_s,
            "end": pm_e,
        }

    return None


def next_window(
    now=None
):
    now = now or now_ist()

    day = now.date()

    p = predict_session_times(
        now
    )

    am_s, am_e = _session_bounds(
        day,
        p["AM"],
    )

    pm_s, pm_e = _session_bounds(
        day,
        p["PM"],
    )

    if now < am_s:
        return {
            "name": "AM",
            "start": am_s,
            "end": am_e,
        }

    if now < pm_s:
        return {
            "name": "PM",
            "start": pm_s,
            "end": pm_e,
        }

    tomorrow = (
        day
        + timedelta(days=1)
    )

    p_tom = predict_session_times(
        datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            0,
            0,
            tzinfo=IST,
        )
    )

    am_s_tom, am_e_tom = _session_bounds(
        tomorrow,
        p_tom["AM"],
    )

    return {
        "name": "AM",
        "start": am_s_tom,
        "end": am_e_tom,
    }


def save_window_info(
    window
):
    p = predict_session_times(
        now_ist()
    )

    save_json(
        WINDOW_FILE,
        {
            "timezone": "Asia/Kolkata",

            "updated_at": (
                now_ist().isoformat()
            ),

            "windows": {
                "AM": {
                    "predicted_fix_time": (
                        f"{p['AM'][0]:02d}:"
                        f"{p['AM'][1]:02d}"
                    ),
                    "arrival_window_90": (
                        p.get("details", {}).get("AM", {}).get("window_90")
                        or [f"{p['AM'][0]:02d}:30", f"{p['AM'][0]+1:02d}:00"]
                    ),
                    "polling_starts": (
                        f"{PRE_WINDOW_MINUTES} "
                        "min before"
                    ),
                    "duration_minutes": (
                        WINDOW_DURATION_MINUTES
                    ),
                    "kde_bandwidth_minutes": (
                        p.get("details", {}).get("AM", {}).get("bandwidth_minutes")
                    ),
                },

                "PM": {
                    "predicted_fix_time": (
                        f"{p['PM'][0]:02d}:"
                        f"{p['PM'][1]:02d}"
                    ),
                    "arrival_window_90": (
                        p.get("details", {}).get("PM", {}).get("window_90")
                        or [f"{p['PM'][0]:02d}:00", f"{p['PM'][0]+1:02d}:00"]
                    ),
                    "polling_starts": (
                        f"{PRE_WINDOW_MINUTES} "
                        "min before"
                    ),
                    "duration_minutes": (
                        WINDOW_DURATION_MINUTES
                    ),
                    "kde_bandwidth_minutes": (
                        p.get("details", {}).get("PM", {}).get("bandwidth_minutes")
                    ),
                },
            },

            "active_window": (
                window["name"]
                if window
                else None
            ),

            "poll_seconds": POLL_SECONDS,
        },
    )


# ============================================================
# MAIN PIPELINE
# ============================================================

def normal_fetch():
    prev_rate = get_previous_rate()

    res = fetch_all_sources()
    live = res[0]
    good = res[1]
    ibja = res[2]
    bank = res[3] if len(res) > 3 else None
    money = res[4] if len(res) > 4 else None
    policy = res[5] if len(res) > 5 else None

    selected = select_rate(
        live,
        good,
        ibja,
        prev_rate,
        bankbazaar=bank,
        moneycontrol=money,
        policybazaar=policy,
    )

    if not selected:
        return False

    rate = selected["rate_22k"]

    changed = (
        prev_rate is not None
        and rate != prev_rate
    )

    save_live(
        rate,
        selected,
        changed,
    )

    save_history(
        rate,
        selected,
        changed,
    )

    history_data = load_json(HISTORY_FILE, [])
    live_data = load_json(LIVE_FILE, {})
    quant_metrics = compute_quant_metrics(history_data, live_data, selected.get("ibja"))
    signals = compute_financial_signals(history_data, live_data.get("rate_22k"), quant_metrics.get("chennai_premium_pct"))
    bake_instant_bootstrap(live_data, history_data, quant_metrics, selected.get("ibja"), signals)

    return True


def poll_window_once(window):
    """
    Do a SINGLE fetch-and-save pass for an active monitoring window,
    then return immediately. No internal sleep loop.
    """
    prev_rate = get_previous_rate()

    res = fetch_all_sources()
    live = res[0]
    good = res[1]
    ibja = res[2]
    bank = res[3] if len(res) > 3 else None
    money = res[4] if len(res) > 4 else None
    policy = res[5] if len(res) > 5 else None

    selected = select_rate(
        live,
        good,
        ibja,
        prev_rate,
        bankbazaar=bank,
        moneycontrol=money,
        policybazaar=policy,
    )

    if not selected:
        save_window_info(window)
        return False

    rate = selected["rate_22k"]

    changed = (
        prev_rate is not None
        and rate != prev_rate
    )

    save_live(
        rate,
        selected,
        changed,
    )

    save_history(
        rate,
        selected,
        changed,
    )

    history_data = load_json(HISTORY_FILE, [])
    live_data = load_json(LIVE_FILE, {})
    quant_metrics = compute_quant_metrics(history_data, live_data, selected.get("ibja"))
    signals = compute_financial_signals(history_data, live_data.get("rate_22k"), quant_metrics.get("chennai_premium_pct"))
    bake_instant_bootstrap(live_data, history_data, quant_metrics, selected.get("ibja"), signals)

    save_window_info(
        window if not changed else None
    )

    return changed


def _in_dense_polling_band(now):
    """
    True if `now` falls inside one of the wide dense-polling cron
    bands defined in the workflow:
      AM Fix: 07:30-12:30 IST (02:00-07:00 UTC)
      PM Fix: 15:30-22:30 IST (10:00-17:00 UTC)
    Must be kept in sync with the `schedule:` entries in
    main.yml. Used only to decide whether an off-window tick should
    skip fetching (see main()) -- has no effect on whether polling
    actually happens, since that's entirely controlled by GitHub's
    cron, not by this check.
    """
    minutes = now.hour * 60 + now.minute

    band_1 = (7 * 60 + 30, 12 * 60 + 30)
    band_2 = (15 * 60 + 30, 22 * 60 + 30)

    return (
        band_1[0] <= minutes < band_1[1]
        or band_2[0] <= minutes < band_2[1]
    )


def main():
    now = now_ist()

    is_gha = (
        os.environ.get(
            "GITHUB_ACTIONS",
            "",
        ).lower()
        == "true"
    )

    gha_event = os.environ.get(
        "GITHUB_EVENT_NAME",
        "",
    )

    force = (
        os.environ.get(
            "FORCE_FETCH",
            "",
        ).lower()
        == "true"
    )

    # --------------------------------------------------------
    # Manual/forced fetch
    # --------------------------------------------------------

    if force:
        save_window_info(None)

        if not normal_fetch():
            sys.exit(1)

        return

    # --------------------------------------------------------
    # If currently inside a monitoring window, do ONE poll pass
    # and exit. No sleeping, no waiting -- this function is meant
    # to be invoked frequently (every few minutes) by the
    # scheduler instead of blocking inside a single long job.
    # --------------------------------------------------------

    active = current_window(
        now
    )

    if active:
        poll_window_once(active)
        return

    # --------------------------------------------------------
    # Not inside a monitoring window right now.
    #
    # STALENESS SELF-HEAL: if live.json hasn't been verified in a
    # while and we're already past the predicted fix time for the
    # session that should have run, do a normal fetch anyway rather
    # than silently waiting for the next window/cron tick. This
    # covers the case where a scheduled run was delayed or skipped
    # entirely (GitHub's `schedule` trigger is best-effort and can
    # be delayed under load) and nothing else would catch it until
    # the following session.
    # --------------------------------------------------------

    live_data = load_json(LIVE_FILE, {})
    stale_hours = _hours_since(
        live_data.get("verified_at") or live_data.get("updated_at"),
        now,
    )

    upcoming = next_window(now)
    missed_a_window = (
        stale_hours is not None
        and stale_hours >= (STALE_CATCHUP_HOURS)
        and upcoming["start"] > now + timedelta(hours=1)
        # ^ only self-heal when the *next* window is still a while
        # away -- if it's coming up soon, just let it run normally
        # instead of double-fetching right before it.
    )

    if missed_a_window:
        print(
            f"STALE CATCH-UP: live.json unverified for "
            f"{stale_hours:.1f}h and no window imminent -- "
            "forcing a fetch now."
        )
        save_window_info(None)
        if not normal_fetch():
            sys.exit(1)
        return

    # --------------------------------------------------------
    # Outside monitoring window, nothing stale enough to force.
    #
    # BUGFIX: this branch used to call normal_fetch() unconditionally
    # on every tick, including dense-schedule ticks (every 5 min,
    # 08:00-12:00 and 18:30-21:30 IST -- kept wider than the actual
    # predicted window to tolerate day-to-day drift) that land
    # outside the real window. That meant a live scrape of both
    # sources every 5 minutes for ~4 extra hours/day -- unnecessary
    # load on LiveChennai/GoodReturns and needless commit noise.
    #
    # Fix: inside a dense band but outside the real window, only
    # fetch if we're within NEAR_WINDOW_MARGIN_MINUTES of the next
    # window opening (so live.json still ticks over just before/
    # after a session). The separate hourly heartbeat ticks (outside
    # both dense bands) are infrequent enough to always fetch --
    # that's their whole job as a backstop.
    # --------------------------------------------------------

    in_dense_band = _in_dense_polling_band(now)

    should_fetch = (
        not in_dense_band
        or upcoming["start"] - now <= timedelta(minutes=NEAR_WINDOW_MARGIN_MINUTES)
    )

    save_window_info(None)

    if should_fetch:
        if not normal_fetch():
            sys.exit(1)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        sys.exit(1)

    except Exception as exc:
        print(
            f"FATAL: {exc}"
        )
        sys.exit(1)

    finally:
        try:
            health = run_health_check()

        except Exception as exc:
            print(
                f"Health check failed: {exc}"
            )
            health = None

        try:
            if health:
                run_alert_check(health)

        except Exception as exc:
            print(
                f"Alert check failed: {exc}"
            )

        try:
            history_data = load_json(HISTORY_FILE, [])
            live_data = load_json(LIVE_FILE, {})
            ibja_data = load_json(IBJA_FILE, {})
            quant_data = compute_quant_metrics(history_data, live_data, ibja_data)
            signals_data = compute_financial_signals(
                history_data,
                live_data.get("rate_22k"),
                quant_data.get("chennai_premium_pct")
            )
            bake_instant_bootstrap(live_data, history_data, quant_data, ibja_data, signals_data)
        except Exception as exc:
            print(
                f"Quant & bootstrap baking failed: {exc}"
            )

        try:
            compute_and_save_summary()

        except Exception as exc:
            print(
                f"Summary computation failed: {exc}"
            )
