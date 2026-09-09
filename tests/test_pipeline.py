#!/usr/bin/env python3
"""
Comprehensive Test Suite for Chennai 22K Gold Data Pipeline & Quant Engine:
1. IBJA scraping & fallback mirrors resilience
2. Bayesian Multi-Source Consensus calculation & outlier filtering
3. Quantitative Risk Engine (30d Realized Volatility & 1-day 95% Parametric VaR)
4. Gaussian KDE fix timing mode & 90% confidence interval
5. Instant-load cache generation (data/bootstrap.json & index.html pre-baking)
6. End-to-end pipeline execution with schema validation
"""

import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import update_gold


def test_ibja_fetching_and_fallbacks():
    print("Testing IBJA fetching and fallbacks...")
    ibja_data = update_gold.fetch_ibja()
    assert ibja_data is not None, "fetch_ibja() returned None"
    assert "rate_22k" in ibja_data, "rate_22k missing in IBJA data"
    assert "rate_24k" in ibja_data, "rate_24k missing in IBJA data"
    assert update_gold.valid_gold_rate(ibja_data["rate_22k"]), f"Invalid IBJA 22k rate: {ibja_data['rate_22k']}"
    assert update_gold.valid_gold_rate(ibja_data["rate_24k"]), f"Invalid IBJA 24k rate: {ibja_data['rate_24k']}"
    assert "status" in ibja_data, "status missing in IBJA data"
    print(f"  IBJA 22K: ₹{ibja_data['rate_22k']}/g | 24K: ₹{ibja_data['rate_24k']}/g | Source: {ibja_data.get('source')}")

    # Test Chennai Premium computation
    chennai_rate = 14190
    prem_amt, prem_pct = update_gold.compute_chennai_premium(chennai_rate, ibja_data["rate_22k"])
    assert prem_amt is not None, "Premium amount should not be None"
    assert prem_pct is not None, "Premium pct should not be None"
    print(f"  Chennai Retail Premium vs IBJA: +₹{prem_amt}/g ({prem_pct:+.2f}%)")
    print("✓ IBJA fetch and premium calculation PASSED\n")


def test_chennai_submarket_spreads():
    print("Testing Chennai Sub-Market Basis & Wholesale Spread Engine...")
    rate_22k = 14270
    sub = update_gold.compute_submarket_spreads(rate_22k)
    assert sub is not None, "compute_submarket_spreads returned None"
    assert sub["sowcarpet_wholesale_22k"] == rate_22k - 45, f"Expected {rate_22k - 45}, got {sub['sowcarpet_wholesale_22k']}"
    expected_sow_pct = round((-45.0 / rate_22k) * 100.0, 2)
    assert sub["sowcarpet_discount_pct"] == expected_sow_pct, f"Expected {expected_sow_pct}, got {sub['sowcarpet_discount_pct']}"
    assert sub["retail_showroom_spread"] == 180, f"Expected 180, got {sub['retail_showroom_spread']}"
    assert sub["retail_showroom_rate_22k"] == rate_22k + 180, f"Expected {rate_22k + 180}, got {sub['retail_showroom_rate_22k']}"
    expected_show_pct = round((180.0 / rate_22k) * 100.0, 2)
    assert sub["retail_showroom_markup_pct"] == expected_show_pct, f"Expected {expected_show_pct}, got {sub['retail_showroom_markup_pct']}"

    # Test Regional Basis Parity
    payload = sub["submarket_spreads"]
    assert "regional_parity" in payload
    cbe = payload["regional_parity"]["coimbatore"]
    assert cbe["rate_22k"] == rate_22k - 15
    assert cbe["basis_spread"] == -15
    assert cbe["parity_status"] == "Discount"

    mad = payload["regional_parity"]["madurai"]
    assert mad["rate_22k"] == rate_22k + 15
    assert mad["basis_spread"] == 15
    assert mad["parity_status"] == "Premium"

    salem = payload["regional_parity"]["salem"]
    assert salem["rate_22k"] == rate_22k - 10
    assert salem["basis_spread"] == -10
    assert salem["parity_status"] == "Discount"

    # Test Bullion-to-Retail Value Chain Arbitrage
    arb = payload["value_chain_arbitrage"]
    assert arb["gross_spread_amount"] == 180 - (-45)  # 225
    expected_arb_pct = round((225.0 / (rate_22k - 45)) * 100.0, 2)
    assert arb["gross_spread_pct"] == expected_arb_pct

    # Test Edge cases
    edge = update_gold.compute_submarket_spreads(0)
    assert edge["sowcarpet_wholesale_22k"] is None
    assert edge["retail_showroom_spread"] is None

    print(f"  Sowcarpet Wholesale 22K: ₹{sub['sowcarpet_wholesale_22k']}/g ({sub['sowcarpet_discount_pct']}%)")
    print(f"  T. Nagar Showroom Retail: ₹{sub['retail_showroom_rate_22k']}/g (+{sub['retail_showroom_markup_pct']}%)")
    print(f"  Coimbatore Basis: ₹{cbe['rate_22k']}/g ({cbe['basis_spread']:+d}/g)")
    print(f"  Madurai Basis: ₹{mad['rate_22k']}/g ({mad['basis_spread']:+d}/g)")
    print(f"  Salem Basis: ₹{salem['rate_22k']}/g ({salem['basis_spread']:+d}/g)")
    print(f"  Value Chain Arbitrage: ₹{arb['gross_spread_amount']}/g ({arb['gross_spread_pct']}%)")
    print("✓ Chennai Sub-Market Basis & Wholesale Spread Engine PASSED\n")


def test_bayesian_consensus():
    print("Testing Bayesian Multi-Source Consensus Engine...")

    # Case 1: High agreement across all 3 sources
    sources_agree = {
        "livechennai": {"rate_22k": 14190},
        "goodreturns": {"rate_22k": 14190},
        "ibja": {"rate_22k": 13988}, # retail implied ~14190
    }
    c1 = update_gold.calculate_bayesian_consensus(sources_agree, previous_rate=14190)
    assert c1["valid"] is True
    assert c1["consensus_rate"] == 14190
    assert c1["confidence"] >= 95, f"Expected high confidence, got {c1['confidence']}"
    assert c1["sources_count"] == 3
    print(f"  Case 1 (All Agree): Consensus ₹{c1['consensus_rate']}, Confidence {c1['confidence']}%")

    # Case 2: Outlier rejection via Modified Z-score (MAD)
    sources_outlier = {
        "livechennai": {"rate_22k": 14190},
        "goodreturns": {"rate_22k": 25000}, # Extreme anomalous spike
        "ibja": {"rate_22k": 13988},
    }
    c2 = update_gold.calculate_bayesian_consensus(sources_outlier, previous_rate=14190)
    assert c2["valid"] is True
    assert c2["consensus_rate"] == 14190
    assert c2["breakdown"]["goodreturns"]["is_outlier"] is True, "Outlier was not flagged!"
    assert c2["breakdown"]["goodreturns"]["effective_weight"] == 0.0, "Outlier was not zero-weighted!"
    assert c2["sources_count"] == 2
    print(f"  Case 2 (Outlier Glitch Filtered): GoodReturns flagged outlier={c2['breakdown']['goodreturns']['is_outlier']} (Mod-Z: {c2['breakdown']['goodreturns']['modified_z']}), Consensus ₹{c2['consensus_rate']}, Confidence {c2['confidence']}%")

    # Case 3: Missing GoodReturns (only LiveChennai + IBJA)
    sources_partial = {
        "livechennai": {"rate_22k": 14190},
        "ibja": {"rate_22k": 13988},
    }
    c3 = update_gold.calculate_bayesian_consensus(sources_partial, previous_rate=14190)
    assert c3["valid"] is True
    assert c3["consensus_rate"] == 14190
    assert c3["sources_count"] == 2
    print(f"  Case 3 (2 Sources): Consensus ₹{c3['consensus_rate']}, Confidence {c3['confidence']}%")
    print("✓ Bayesian Multi-Source Consensus PASSED\n")


def test_quantitative_risk_engine():
    print("Testing Quantitative Risk Engine (Volatility & VaR)...")
    history_records = update_gold.load_json(update_gold.HISTORY_FILE, [])
    live_record = update_gold.load_json(update_gold.LIVE_FILE, {})
    ibja_record = update_gold.load_json(update_gold.IBJA_FILE, {})

    metrics = update_gold.compute_quant_metrics(history_records, live_record, ibja_record)
    assert metrics is not None
    assert "volatility_30d_annualized" in metrics
    assert "volatility_30d_pct" in metrics
    assert "var_95_1d_amount" in metrics
    assert "var_95_1d_pct" in metrics
    assert "var_95_1d_8g_amount" in metrics

    # Mathematically verify VaR formula:
    # VaR_95 = 1.645 * (vol_annual / sqrt(252)) * rate_22k
    expected_var = 1.645 * (metrics["volatility_30d_annualized"] / math.sqrt(252)) * metrics["rate_22k"]
    assert abs(metrics["var_95_1d_amount"] - expected_var) < 0.1, f"VaR mismatch: got {metrics['var_95_1d_amount']}, expected {expected_var}"

    print(f"  30-Day Realized Annualized Volatility: {metrics['volatility_30d_pct']}%")
    print(f"  1-Day 95% Parametric VaR: ₹{metrics['var_95_1d_amount']:.2f}/g ({metrics['var_95_1d_pct']:.2f}%)")
    print(f"  1-Day 95% 8g Sovereign VaR: ₹{metrics['var_95_1d_8g_amount']:.2f}")
    print(f"  95% Daily Price Range: [₹{metrics['var_95_1d_lower_bound']}, ₹{metrics['var_95_1d_upper_bound']}]")
    print("✓ Quantitative Risk Engine PASSED\n")


def test_probabilistic_fix_timing():
    print("Testing Probabilistic Fix Timing with Gaussian KDE...")
    predictions = update_gold.predict_session_times()
    assert "AM" in predictions
    assert "PM" in predictions
    assert "details" in predictions

    am_details = predictions["details"]["AM"]
    pm_details = predictions["details"]["PM"]
    assert "window_90" in am_details
    assert "window_90" in pm_details

    print(f"  AM Predicted Fix: {predictions['AM'][0]:02d}:{predictions['AM'][1]:02d} | 90% Confidence Arrival Window: {am_details['window_90']}")
    print(f"  PM Predicted Fix: {predictions['PM'][0]:02d}:{predictions['PM'][1]:02d} | 90% Confidence Arrival Window: {pm_details['window_90']}")
    print("✓ Probabilistic Fix Timing PASSED\n")


def test_instant_cache_generator():
    print("Testing Instant Cache Generator & Bootstrap Baking...")
    live_data = update_gold.load_json(update_gold.LIVE_FILE, {})
    history_data = update_gold.load_json(update_gold.HISTORY_FILE, [])
    quant_metrics = update_gold.load_json(update_gold.QUANT_FILE, {})
    ibja_data = update_gold.load_json(update_gold.IBJA_FILE, {})

    baked = update_gold.bake_instant_bootstrap(live_data, history_data, quant_metrics, ibja_data)
    assert update_gold.BOOTSTRAP_FILE.exists(), "bootstrap.json was not created"
    
    # Verify bootstrap.json contents
    boot_json = update_gold.load_json(update_gold.BOOTSTRAP_FILE, {})
    assert "live" in boot_json
    assert "history" in boot_json
    assert "quant" in boot_json
    assert "ibja" in boot_json
    assert "baked_at" in boot_json

    # Verify index.html contains gold-bootstrap script tag
    html_content = update_gold.INDEX_HTML_FILE.read_text(encoding="utf-8")
    assert '<script id="gold-bootstrap" type="application/json">' in html_content, "index.html missing bootstrap script tag"
    print(f"  bootstrap.json size: {update_gold.BOOTSTRAP_FILE.stat().st_size} bytes")
    print("✓ Instant Cache Generator PASSED\n")


def test_full_pipeline_run():
    print("Testing Full Pipeline Run (save_live, summary, quant, windows)...")
    prev_rate = update_gold.get_previous_rate()
    res = update_gold.fetch_all_sources()
    live, good, ibja = res[0], res[1], res[2]
    bank = res[3] if len(res) > 3 else None
    money = res[4] if len(res) > 4 else None
    policy = res[5] if len(res) > 5 else None
    selected = update_gold.select_rate(live, good, ibja, prev_rate, bankbazaar=bank, moneycontrol=money, policybazaar=policy)
    assert selected is not None, "select_rate returned None"

    rate = selected["rate_22k"]
    changed = prev_rate is not None and rate != prev_rate
    update_gold.save_live(rate, selected, changed)
    update_gold.save_window_info(None)

    # Verify live.json explicit metadata & ISO 8601 timestamps
    live_json = update_gold.load_json(update_gold.LIVE_FILE, {})
    assert "date" in live_json and re.match(r"^\d{4}-\d{2}-\d{2}$", live_json["date"]), f"Invalid date: {live_json.get('date')}"
    assert "time" in live_json and re.match(r"^\d{2}:\d{2}:\d{2}$", live_json["time"]), f"Invalid time: {live_json.get('time')}"
    assert live_json.get("session") in ("AM", "PM"), f"session must be 'AM' or 'PM', got: {live_json.get('session')}"
    assert "last_checked_at" in live_json and datetime.fromisoformat(live_json["last_checked_at"]), "last_checked_at must be valid ISO 8601"
    assert "timestamp" in live_json and datetime.fromisoformat(live_json["timestamp"]), "timestamp must be valid ISO 8601"
    assert "updated_at" in live_json and datetime.fromisoformat(live_json["updated_at"]), "updated_at must be valid ISO 8601"
    assert "verified_at" in live_json and datetime.fromisoformat(live_json["verified_at"]), "verified_at must be valid ISO 8601"

    # Verify quantitative metadata
    assert "ibja" in live_json, "ibja missing from live.json"
    assert "consensus" in live_json, "consensus missing from live.json"
    assert "chennai_premium_amount" in live_json, "chennai_premium_amount missing from live.json"
    assert "chennai_premium_pct" in live_json, "chennai_premium_pct missing from live.json"
    assert "sowcarpet_wholesale_22k" in live_json, "sowcarpet_wholesale_22k missing from live.json"
    assert "sowcarpet_discount_pct" in live_json, "sowcarpet_discount_pct missing from live.json"
    assert "retail_showroom_spread" in live_json, "retail_showroom_spread missing from live.json"
    assert "submarket_spreads" in live_json, "submarket_spreads missing from live.json"

    # Verify atomic bootstrap baking and synchrony with live.json
    history_data = update_gold.load_json(update_gold.HISTORY_FILE, [])
    quant_data = update_gold.compute_quant_metrics(history_data, live_json, ibja)
    signals_data = update_gold.compute_financial_signals(history_data, live_json.get("rate_22k"), quant_data.get("chennai_premium_pct"))
    boot_payload = update_gold.bake_instant_bootstrap(live_json, history_data, quant_data, ibja, signals_data)
    assert update_gold.BOOTSTRAP_FILE.exists(), "bootstrap.json was not created"
    boot_json = update_gold.load_json(update_gold.BOOTSTRAP_FILE, {})
    assert datetime.fromisoformat(boot_json["baked_at"]), "baked_at must be valid ISO 8601"
    assert boot_json["live"]["session"] in ("AM", "PM"), f"bootstrap live.session invalid: {boot_json['live'].get('session')}"
    assert boot_json["live"]["last_checked_at"] == live_json["last_checked_at"]
    assert boot_json["live"]["rate_22k"] == live_json["rate_22k"]

    # Verify monitoring_windows.json
    windows_json = update_gold.load_json(update_gold.WINDOW_FILE, {})
    assert "arrival_window_90" in windows_json["windows"]["AM"], "arrival_window_90 missing from AM window"
    assert "arrival_window_90" in windows_json["windows"]["PM"], "arrival_window_90 missing from PM window"

    # Run health check & summary
    health = update_gold.run_health_check()
    assert health is not None
    assert health["source_count"] >= 2, f"Expected >= 2 sources, got {health['source_count']}"

    update_gold.compute_and_save_summary()
    summary_json = update_gold.load_json(update_gold.SUMMARY_FILE, {})
    assert "quant" in summary_json, "quant metrics missing from summary.json"

    print("✓ Full Pipeline Run PASSED\n")


if __name__ == "__main__":
    print("============================================================")
    print("RUNNING PIPELINE & DEEPTECH QUANT TEST SUITE")
    print("============================================================")
    test_ibja_fetching_and_fallbacks()
    test_chennai_submarket_spreads()
    test_bayesian_consensus()
    test_quantitative_risk_engine()
    test_probabilistic_fix_timing()
    test_instant_cache_generator()
    test_full_pipeline_run()
    print("============================================================")
    print("ALL TESTS PASSED SUCCESSFULLY (100% GREEN)")
    print("============================================================")
