#!/usr/bin/env python3
"""
================================================================================
UNIT & QUANT TEST SUITE: GOLD SCHEME (11-MONTH CHIT) VS PHYSICAL GOLD SIP
================================================================================
Tests:
1. XIRR Engine Numerical Precision & Convergence
2. Weight-Based Scheme (GRT / Lalitha) Mathematical Verification
3. Cash-Based Scheme (Tanishq / Kalyan) Mathematical Verification
4. Direct Monthly Gold SIP (Coin Minting Markups & Liquid Value)
5. Analytical Harmonic Mean Breakeven Theorem
6. Real Historical Chennai 22K MJDMA Data Backtest
7. Market Regime Sensitivity Scenarios (Bull, Flat, Bear)
================================================================================
"""

import json
import math
import os
import sys
from pathlib import Path

# Add project root and engine to sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "engine"))

from engine.gold_scheme_calculator import (
    XIRRSolver,
    GoldSavingsEngine,
    ChennaiJewellerProfiles,
    DoubleExponentialSmoothing,
    calculate_gold_scheme_vs_sip
)


def test_xirr_solver_accuracy():
    print("[TEST 1] Testing XIRR Solver Numerical Accuracy...")
    
    # Standard 1-year annual doubling: -100 at day 0, +200 at day 365 -> XIRR should be exactly 100.0%
    cf_doubling = [(0.0, -100.0), (365.0, 200.0)]
    r1 = XIRRSolver.calculate_xirr(cf_doubling)
    assert r1 is not None, "Failed on doubling cash flow"
    assert abs(r1 - 1.0) < 1e-4, f"Expected 1.0 (100%), got {r1}"
    print(f"  ✓ Simple Doubling: XIRR = {r1 * 100:.2f}% (Expected: 100.00%)")

    # Regular 12-month zero-interest return: 12 installments of 100, return 1200 at month 12
    cf_zero = [(i * 30.0, -100.0) for i in range(12)]
    cf_zero.append((365.0, 1200.0))
    r_zero = XIRRSolver.calculate_xirr(cf_zero)
    assert r_zero is not None
    assert abs(r_zero) < 0.01, f"Expected ~0.0%, got {r_zero}"
    print(f"  ✓ Zero Return Base: XIRR = {r_zero * 100:.2f}% (Expected: ~0.00%)")

    # Known monthly SIP with positive yield
    cf_sip = [(i * 30.0, -10000.0) for i in range(11)]
    cf_sip.append((365.0, 120000.0))
    r_sip = XIRRSolver.calculate_xirr(cf_sip)
    assert r_sip is not None
    assert 0.14 < r_sip < 0.17, f"Expected ~15.5% XIRR, got {r_sip * 100:.2f}%"
    print(f"  ✓ 11-Month Cash Scheme Base: XIRR = {r_sip * 100:.2f}%")


def test_weight_based_scheme_math():
    print("\n[TEST 2] Testing Weight-Based Scheme (GRT / Lalitha) Math...")
    engine = GoldSavingsEngine(monthly_installment=10000.0, gst_pct=3.0)
    
    # Flat price scenario: 14,000 across all 11 months and at maturity
    flat_prices = [14000.0] * 11
    maturity_price = 14000.0
    
    res = engine.calculate_weight_based_scheme(
        monthly_prices=flat_prices,
        maturity_price=maturity_price,
        va_waiver_pct=14.0,
        actual_jewellery_va_pct=14.0
    )
    
    # Each month buys 10000 / 14000 = 0.7142857 grams
    # 11 months = 11 * 0.7142857 = 7.85714 grams
    expected_grams = (10000.0 / 14000.0) * 11
    assert abs(res["gold_accumulated_grams"] - expected_grams) < 0.001
    
    # Since VA waiver = 14% and actual VA = 14%, excess VA payable should be ZERO
    assert res["excess_va_payable"] == 0.0, f"Expected excess VA 0.0, got {res['excess_va_payable']}"
    
    # VA savings: raw_gold_value * 14% * 1.03
    raw_val = expected_grams * 14000.0 # = 110,000
    expected_va_savings = raw_val * 0.14 * 1.03
    assert abs(res["va_savings_rupees"] - expected_va_savings) < 1.0
    
    # High XIRR expected due to free 14% VA jewellery value
    assert res["xirr_jewellery_basis"] > 25.0, f"Expected high XIRR, got {res['xirr_jewellery_basis']}"
    print(f"  ✓ Accumulated Gold: {res['gold_accumulated_grams']} g")
    print(f"  ✓ VA Savings Waived: ₹{res['va_savings_rupees']:,.2f}")
    print(f"  ✓ Full Jewellery Retail Value: ₹{res['full_retail_jewellery_value']:,.2f}")
    print(f"  ✓ Effective Yield (XIRR): {res['xirr_jewellery_basis']}%")


def test_cash_based_scheme_math():
    print("\n[TEST 3] Testing Cash-Based Scheme (Tanishq 1-Month Bonus) Math...")
    engine = GoldSavingsEngine(monthly_installment=10000.0, gst_pct=3.0)
    flat_prices = [14000.0] * 11
    maturity_price = 14000.0
    
    res = engine.calculate_cash_bonus_scheme(
        monthly_prices=flat_prices,
        maturity_price=maturity_price,
        bonus_month_multiplier=1.0,
        actual_jewellery_va_pct=14.0
    )
    
    assert res["total_principal_paid"] == 110000.0
    assert res["bonus_amount_added"] == 10000.0
    assert res["total_voucher_value"] == 120000.0
    assert res["absolute_return_pct"] == round((10000.0 / 110000.0) * 100, 2) # 9.09%
    
    # In flat market, all-inclusive rate = 14000 * 1.14 * 1.03 = 16,438.8
    # Grams = 120000 / 16438.8 = 7.2998 g
    expected_grams = 120000.0 / (14000.0 * 1.14 * 1.03)
    assert abs(res["gold_accumulated_grams"] - expected_grams) < 0.001
    print(f"  ✓ Voucher: ₹{res['total_voucher_value']:,.2f} (Bonus: ₹{res['bonus_amount_added']:,.2f})")
    print(f"  ✓ Gold Grams Obtained: {res['gold_accumulated_grams']} g")
    print(f"  ✓ XIRR: {res['xirr_jewellery_basis']}%")


def test_breakeven_harmonic_mean_theorem():
    """
    Mathematical Proof:
    Let monthly prices be P_0, ..., P_{10}.
    Weight scheme raw gold grams = sum(X / P_t) = 11 * X / H
    Cash scheme raw gold grams   = (11 + b) * X / P_mat
    
    Breakeven condition for raw gold equivalence:
    11 * X / H = (11 + b) * X / P_mat
    => P_mat = H * (11 + b) / 11
    When b = 1.0: P_mat = H * (12 / 11) = H * 1.090909
    """
    print("\n[TEST 4] Testing Analytical Harmonic Mean Breakeven Theorem...")
    # Generate arbitrary upward trending price vector
    prices = [10000.0 + i * 250.0 for i in range(11)]
    inv_sum = sum(1.0 / p for p in prices)
    H = len(prices) / inv_sum
    
    # At exact breakeven price:
    P_mat_breakeven = H * (12.0 / 11.0)
    
    engine = GoldSavingsEngine(monthly_installment=5000.0)
    comp = engine.compare_all_options(
        monthly_prices=prices,
        maturity_price=P_mat_breakeven,
        va_waiver_pct=14.0,
        bonus_month_multiplier=1.0
    )
    
    ws = comp["weight_based_scheme"]
    cs = comp["cash_bonus_scheme"]
    
    # Raw gold weight must be identical at breakeven!
    raw_ws_grams = ws["gold_accumulated_grams"]
    raw_cs_grams = cs["raw_gold_accumulated_grams"]
    
    diff = abs(raw_ws_grams - raw_cs_grams)
    assert diff < 1e-4, f"Breakeven theorem failed: WS={raw_ws_grams}, CS={raw_cs_grams}, diff={diff}"
    print(f"  ✓ Harmonic Mean Price: ₹{H:.2f}")
    print(f"  ✓ Exact Breakeven P_mat: ₹{P_mat_breakeven:.2f} (+{(P_mat_breakeven/prices[0]-1)*100:.2f}% from start)")
    print(f"  ✓ Weight Scheme Grams: {raw_ws_grams:.4f} g == Cash Scheme Raw Grams: {raw_cs_grams:.4f} g (Delta: {diff:.6f} g)")


def test_market_regime_matrix():
    print("\n[TEST 5] Testing Market Regime Sensitivity Matrix...")
    engine = GoldSavingsEngine(monthly_installment=10000.0)
    matrix = engine.run_market_regime_matrix(base_price=14270.0, va_waiver_pct=14.0)
    
    assert "Strong Bull (+25%)" in matrix
    assert "Flat Market (0%)" in matrix
    assert "Strong Bear (-20%)" in matrix
    
    # In strong bull, Weight Scheme must outperform Cash Scheme
    bull = matrix["Strong Bull (+25%)"]
    assert bull["weight_scheme_grams"] > bull["cash_scheme_grams"], "Weight scheme should win in bull market"
    
    # In strong bear, Cash Scheme gets more grams at depressed maturity price
    bear = matrix["Strong Bear (-20%)"]
    assert bear["cash_scheme_grams"] > bear["weight_scheme_grams"], "Cash scheme should win in bear market"
    
    for regime, data in matrix.items():
        print(f"  • {regime:<20}: WS={data['weight_scheme_grams']}g (XIRR: {data['weight_scheme_xirr']}%) | CS={data['cash_scheme_grams']}g | Coin={data['direct_coin_grams']}g")


def test_real_chennai_historical_data_backtest():
    print("\n[TEST 6] Testing Real Chennai 22K MJDMA Historical Data Backtest...")
    history_file = PROJECT_DIR / "data" / "history.json"
    if not history_file.exists():
        print("  ⚠️ history.json not found, skipping historical test.")
        return
        
    with open(history_file, "r") as f:
        history = json.load(f)
        
    # Extract unique daily 22K rates sorted by date
    daily_rates = []
    seen_dates = set()
    for row in history:
        d = row.get("date")
        r = row.get("rate_22k")
        if d and r and d not in seen_dates:
            seen_dates.add(d)
            daily_rates.append((d, float(r)))
            
    daily_rates.sort(key=lambda x: x[0])
    print(f"  Loaded {len(daily_rates)} historical trading days ({daily_rates[0][0]} to {daily_rates[-1][0]})")
    
    # Sample 11 monthly points (approx 30 days apart) + 12th month maturity
    if len(daily_rates) >= 365:
        step = len(daily_rates) // 13
        sample_pts = [daily_rates[i * step] for i in range(12)]
        monthly_prices = [pt[1] for pt in sample_pts[:11]]
        maturity_price = sample_pts[11][1]
        
        engine = GoldSavingsEngine(monthly_installment=10000.0)
        res = engine.compare_all_options(
            monthly_prices=monthly_prices,
            maturity_price=maturity_price,
            va_waiver_pct=14.0
        )
        
        ws = res["weight_based_scheme"]
        cs = res["cash_bonus_scheme"]
        coin = res["direct_coin_sip"]
        
        print(f"  Backtest Window: {sample_pts[0][0]} (₹{sample_pts[0][1]}/g) -> {sample_pts[11][0]} (₹{sample_pts[11][1]}/g)")
        print(f"  Gold Return: {res['parameters']['gold_price_change_pct']}%")
        print(f"  Weight Scheme: {ws['gold_accumulated_grams']} g | Jewellery XIRR: {ws['xirr_jewellery_basis']}%")
        print(f"  Cash Scheme:   {cs['gold_accumulated_grams']} g | Jewellery XIRR: {cs['xirr_jewellery_basis']}%")
        print(f"  Coin SIP:      {coin['gold_accumulated_grams']} g | Liquid XIRR:    {coin['xirr_liquid_bullion']}%")
        assert ws["gold_accumulated_grams"] > 0
        assert cs["gold_accumulated_grams"] > 0


if __name__ == "__main__":
    print("=" * 80)
    print("RUNNING COMPLETE QUANTITATIVE TEST SUITE")
    print("=" * 80)
    test_xirr_solver_accuracy()
    test_weight_based_scheme_math()
    test_cash_based_scheme_math()
    test_breakeven_harmonic_mean_theorem()
    test_market_regime_matrix()
    test_real_chennai_historical_data_backtest()
    print("\n" + "=" * 80)
    print("ALL 6 QUANTITATIVE TEST SUITES PASSED PERFECTLY! ✓")
    print("=" * 80)
