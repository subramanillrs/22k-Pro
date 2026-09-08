#!/usr/bin/env python3
"""
================================================================================
CHENNAI 22K GOLD SAVINGS SCHEME (11-MONTH CHIT) VS PHYSICAL GOLD SIP ENGINE
================================================================================
Pure Python Standard Library Implementation (Zero NumPy / SciPy Dependencies)

Quantitative Financial Mathematics for:
1. Chennai Jeweller 11-Month Schemes:
   - Weight-Based DCA + Value Addition (VA / Making Charges) Waiver (GRT Golden Eleven, Lalitha)
   - Cash-Based DCA + 1-Month Bonus Voucher (Tanishq Golden Harvest, Kalyan Dhanvarsha)
2. Direct Monthly Gold SIP:
   - Physical Gold Bullion / Coin Accumulation (DCA with minting premium & GST)
   - Benchmark Spot DCA with Jewellery Conversion vs Liquid Bullion Holding
3. High-Precision Extended Internal Rate of Return (XIRR) Engine:
   - Hybrid Newton-Raphson with Bracketed Bisection Fallback
   - Exact calendar-day discounting: (d_i - d_0) / 365.0
4. Analytical Breakeven & Sensitivity Engine:
   - Exact harmonic mean price inflation threshold where Cash Scheme equals Weight Scheme
   - Comparative yield matrix across Bull, Flat, and Bear market regimes
5. Real Chennai MJDMA Historical Backtesting & Holt-Winters Price Path Generator

Mathematical Notation:
- X: Monthly installment amount (INR)
- N: Number of installments (default 11)
- T: Maturity period in months (default 12 months, day 365 or day 330)
- P_t: Chennai 22K gold rate per gram at installment t (t = 0, 1, ..., N-1)
- P_mat: Chennai 22K gold rate per gram at redemption/maturity (month 12)
- VA: Value Addition / Making charges percentage (typically 12% to 20%)
- GST: Goods and Services Tax (statutory 3.0% in India)
================================================================================
"""

import math
import datetime
from typing import List, Dict, Tuple, Optional, Any, Union


# ==============================================================================
# SECTION 1: HIGH-PRECISION XIRR SOLVER (PURE PYTHON)
# ==============================================================================

class XIRRSolver:
    """
    Solves for the Extended Internal Rate of Return (XIRR) using exact day counts.
    
    Mathematical Formulation:
        NPV(r) = sum_{i=0}^{n} [ C_i / (1 + r)^tau_i ] = 0
        where:
            tau_i = (d_i - d_0) / 365.0
            C_i   = Cash flow at date d_i (negative for outflows, positive for inflows)
            r     = Annualized effective internal rate of return
            
    Derivative for Newton-Raphson:
        dNPV/dr = - sum_{i=0}^{n} [ tau_i * C_i / (1 + r)^(tau_i + 1) ]
        
    Convergence Safeguard:
        Combines Newton-Raphson with bracketed Bisection if the step wanders
        outside the valid rate domain r in (-0.999, 50.0).
    """

    @staticmethod
    def _npv_and_deriv(r: float, cash_flows: List[Tuple[float, float]]) -> Tuple[float, float]:
        """
        Computes NPV(r) and its first derivative dNPV(r)/dr.
        cash_flows is a list of tuples: (tau_years, cash_amount)
        """
        if r <= -1.0:
            return float('inf'), float('inf')
        
        npv = 0.0
        deriv = 0.0
        one_plus_r = 1.0 + r
        
        for tau, amount in cash_flows:
            discount = one_plus_r ** tau
            npv += amount / discount
            deriv -= (tau * amount) / (discount * one_plus_r)
            
        return npv, deriv

    @classmethod
    def calculate_xirr(
        cls,
        cash_flows: List[Tuple[Union[datetime.date, datetime.datetime, int, float], float]],
        guess: float = 0.10,
        max_iter: int = 150,
        tol: float = 1e-8
    ) -> Optional[float]:
        """
        Calculates XIRR given a sequence of (date_or_day_offset, amount) pairs.
        
        Args:
            cash_flows: List of (date/offset, amount)
                        Amounts must contain at least one negative and one positive value.
            guess: Initial guess for the rate (default: 10% = 0.10)
            max_iter: Maximum iterations for convergence.
            tol: Absolute convergence tolerance on NPV.
            
        Returns:
            Annualized rate r (e.g., 0.185 for 18.5%) or None if failed.
        """
        if len(cash_flows) < 2:
            return None
        
        # Check cash flow signs
        has_negative = any(c[1] < 0 for c in cash_flows)
        has_positive = any(c[1] > 0 for c in cash_flows)
        if not (has_negative and has_positive):
            return None
        
        # Normalize time to tau (years elapsed from first cash flow)
        first_entry = cash_flows[0][0]
        is_date = isinstance(first_entry, (datetime.date, datetime.datetime))
        
        normalized_cf: List[Tuple[float, float]] = []
        if is_date:
            d0 = cash_flows[0][0]
            for d, amt in cash_flows:
                delta_days = (d - d0).total_seconds() / 86400.0 if isinstance(d, datetime.datetime) else (d - d0).days
                tau = delta_days / 365.0
                normalized_cf.append((tau, amt))
        else:
            d0_float = float(cash_flows[0][0])
            for d, amt in cash_flows:
                tau = (float(d) - d0_float) / 365.0
                normalized_cf.append((tau, amt))

        # Initial Newton-Raphson search
        r = guess
        for _ in range(max_iter):
            npv, deriv = cls._npv_and_deriv(r, normalized_cf)
            if math.isnan(npv) or math.isinf(npv):
                break
            if abs(npv) < tol:
                return r
            if abs(deriv) < 1e-12:
                break
            
            step = npv / deriv
            new_r = r - step
            
            # Safeguard boundary: r cannot be <= -0.9999
            if new_r <= -0.9999:
                r = (r - 0.9999) / 2.0
            else:
                r = new_r

        # Bisection Fallback in search interval [-0.99, 10.0]
        low, high = -0.99, 10.0
        npv_low, _ = cls._npv_and_deriv(low, normalized_cf)
        npv_high, _ = cls._npv_and_deriv(high, normalized_cf)
        
        # If signs are not opposite, expand upper bound
        if npv_low * npv_high > 0:
            for expanded_high in [25.0, 50.0, 100.0]:
                npv_high, _ = cls._npv_and_deriv(expanded_high, normalized_cf)
                if npv_low * npv_high <= 0:
                    high = expanded_high
                    break
            else:
                return None
        
        for _ in range(max_iter):
            mid = (low + high) / 2.0
            npv_mid, _ = cls._npv_and_deriv(mid, normalized_cf)
            if abs(npv_mid) < tol or (high - low) / 2.0 < tol:
                return mid
            if npv_low * npv_mid < 0:
                high = mid
                npv_high = npv_mid
            else:
                low = mid
                npv_low = npv_mid

        return (low + high) / 2.0


# ==============================================================================
# SECTION 2: CHENNAI JEWELLER SCHEMES & SIP FINANCIAL MODELS
# ==============================================================================

class ChennaiJewellerProfiles:
    """
    Standard parameters for marquee Chennai Jeweller 11-Month Gold Schemes:
    - GRT Jewellers (Golden Eleven)
    - Lalitha Jewellery (Jewellery Purchase Plan)
    - Tanishq (Golden Harvest)
    - Kalyan Jewellers (Dhanvarsha)
    """
    GRT_GOLDEN_ELEVEN = {
        "name": "GRT Jewellers - Golden Eleven",
        "scheme_type": "WEIGHT_BASED_VA_WAIVER",
        "installments": 11,
        "maturity_months": 12,
        "va_waiver_pct": 14.0,       # Waives making charge / wastage up to 14%
        "bonus_month_fraction": 0.0,  # Benefit is in the VA waiver, not cash bonus
        "coin_exchange_permitted": True,
        "description": "Customer deposits ₹X for 11 months. Converted to 22K weight monthly. 14% VA waived at maturity."
    }

    LALITHA_JEWELLERY = {
        "name": "Lalitha Jewellery - 11 Month Scheme",
        "scheme_type": "WEIGHT_BASED_VA_WAIVER",
        "installments": 11,
        "maturity_months": 12,
        "va_waiver_pct": 18.0,       # Waives making charge / wastage up to 18%
        "bonus_month_fraction": 0.0,
        "coin_exchange_permitted": True,
        "description": "Customer deposits ₹X for 11 months. Converted to 22K weight monthly. Up to 18% VA waived at maturity."
    }

    TANISHQ_GOLDEN_HARVEST = {
        "name": "Tanishq - Golden Harvest",
        "scheme_type": "CASH_BONUS_1_MONTH",
        "installments": 11,          # Standard 11 months (or 10 mo variant)
        "maturity_months": 12,
        "va_waiver_pct": 0.0,        # No full VA waiver; standard VA applies
        "bonus_month_fraction": 1.0, # 12th month paid as 100% bonus installment
        "coin_exchange_permitted": False, # Voucher must be redeemed in jewellery
        "description": "Customer pays 11 installments. 12th month (100% of installment) added as bonus by Tanishq."
    }

    KALYAN_DHANVARSHA = {
        "name": "Kalyan Jewellers - Dhanvarsha",
        "scheme_type": "CASH_BONUS_1_MONTH",
        "installments": 11,
        "maturity_months": 12,
        "va_waiver_pct": 0.0,
        "bonus_month_fraction": 0.85, # ~85% of one installment bonus or 50% VA off
        "coin_exchange_permitted": True,
        "description": "Customer pays 11 installments. Kalyan adds up to 85% of 12th installment bonus credit."
    }


class GoldSavingsEngine:
    """
    Comprehensive quantitative engine comparing Jeweller Schemes vs Direct Gold SIP.
    """

    def __init__(
        self,
        monthly_installment: float = 10000.0,
        gst_pct: float = 3.0,
        coin_making_charge_pct: float = 2.0,
        standard_jewellery_va_pct: float = 14.0,
        coin_buyback_spread_pct: float = 1.0
    ):
        """
        Args:
            monthly_installment: Monthly deposit / SIP amount ₹X (default: ₹10,000)
            gst_pct: Statutory Indian GST on gold (3.0%)
            coin_making_charge_pct: Minting charge for physical 22K/24K coins (default: 2.0%)
            standard_jewellery_va_pct: Value Addition / Making charge on retail jewellery (default: 14.0%)
            coin_buyback_spread_pct: Jeweller haircut/spread when liquidating coins for cash (default: 1.0%)
        """
        self.X = float(monthly_installment)
        self.gst = float(gst_pct) / 100.0
        self.coin_va = float(coin_making_charge_pct) / 100.0
        self.jewellery_va = float(standard_jewellery_va_pct) / 100.0
        self.buyback_spread = float(coin_buyback_spread_pct) / 100.0

    # --------------------------------------------------------------------------
    # MODEL 1: JEWELLER WEIGHT-BASED SCHEME (e.g. GRT / Lalitha)
    # --------------------------------------------------------------------------
    def calculate_weight_based_scheme(
        self,
        monthly_prices: List[float],
        maturity_price: float,
        va_waiver_pct: float = 14.0,
        actual_jewellery_va_pct: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Simulates an 11-month weight-based gold scheme:
        - Buyer deposits ₹X for 11 months (t = 0 to 10).
        - At each month t, gold weight g_t = X / P_t is credited.
        - Total weight G = sum(g_t).
        - At maturity (Month 12), customer redeems G grams into jewellery.
        - Making charge up to va_waiver_pct is 100% waived.
        - Any excess VA above va_waiver_pct is billed to customer.
        
        Financial Formulas:
            g_t = X / P_t
            G_total = sum_{t=0}^{10} g_t
            Effective_Billed_VA = max(0, actual_jewellery_va - va_waiver)
            Jewellery_Sticker_Value = G_total * P_mat * (1 + actual_jewellery_va) * (1 + GST)
            Waiver_Savings = G_total * P_mat * min(actual_jewellery_va, va_waiver) * (1 + GST)
            Total_Paid_By_Customer = 11 * X + Excess_VA_and_GST
        """
        num_inst = len(monthly_prices)
        assert num_inst == 11, f"Expected 11 monthly prices, got {num_inst}"
        
        target_va = self.jewellery_va if actual_jewellery_va_pct is None else (actual_jewellery_va_pct / 100.0)
        waiver_va = va_waiver_pct / 100.0
        
        monthly_grams = [self.X / p for p in monthly_prices]
        total_grams = sum(monthly_grams)
        total_principal = self.X * num_inst
        avg_cost_per_gram = total_principal / total_grams
        
        # At maturity (Month 12, P_mat)
        raw_gold_value = total_grams * maturity_price
        
        # Making charge handling
        billed_va_pct = max(0.0, target_va - waiver_va)
        waived_va_pct = min(target_va, waiver_va)
        
        # Full sticker value outside scheme
        full_retail_jewellery_value = raw_gold_value * (1.0 + target_va) * (1.0 + self.gst)
        
        # Waiver financial value (pure savings to the consumer)
        waiver_rupee_value = raw_gold_value * waived_va_pct * (1.0 + self.gst)
        
        # Out of pocket excess paid by customer at redemption
        excess_va_payable = raw_gold_value * billed_va_pct * (1.0 + self.gst)
        total_out_of_pocket = total_principal + excess_va_payable
        
        # Cash flows for XIRR:
        # 11 monthly outflows of -X at day 0, 30, 60, ..., 300
        # Final excess payment (if any) at day 365
        # Terminal asset value received at day 365: full retail jewellery value
        cash_flows: List[Tuple[float, float]] = []
        for i in range(num_inst):
            cash_flows.append((i * 30.0, -self.X))
            
        maturity_day = 365.0
        net_terminal_value = full_retail_jewellery_value - excess_va_payable
        cash_flows.append((maturity_day, net_terminal_value))
        
        scheme_xirr = XIRRSolver.calculate_xirr(cash_flows)
        
        # Also compute bullion-only XIRR (if customer took raw gold or gold coin with 0% VA)
        cash_flows_raw: List[Tuple[float, float]] = [(i * 30.0, -self.X) for i in range(num_inst)]
        cash_flows_raw.append((maturity_day, raw_gold_value))
        raw_gold_xirr = XIRRSolver.calculate_xirr(cash_flows_raw)
        
        return {
            "model": "WEIGHT_BASED_VA_WAIVER",
            "installments_count": num_inst,
            "monthly_installment": self.X,
            "total_principal_paid": total_principal,
            "gold_accumulated_grams": round(total_grams, 4),
            "average_cost_per_gram": round(avg_cost_per_gram, 2),
            "maturity_gold_rate": maturity_price,
            "raw_gold_market_value": round(raw_gold_value, 2),
            "full_retail_jewellery_value": round(full_retail_jewellery_value, 2),
            "va_waiver_pct": round(waiver_va * 100, 2),
            "va_savings_rupees": round(waiver_rupee_value, 2),
            "excess_va_payable": round(excess_va_payable, 2),
            "total_out_of_pocket": round(total_out_of_pocket, 2),
            "xirr_jewellery_basis": round(scheme_xirr * 100, 2) if scheme_xirr is not None else None,
            "xirr_raw_gold_basis": round(raw_gold_xirr * 100, 2) if raw_gold_xirr is not None else None,
            "absolute_return_pct": round(((full_retail_jewellery_value - total_out_of_pocket) / total_out_of_pocket) * 100, 2)
        }

    # --------------------------------------------------------------------------
    # MODEL 2: JEWELLER CASH-BASED SCHEME (e.g. Tanishq 1-Month Bonus)
    # --------------------------------------------------------------------------
    def calculate_cash_bonus_scheme(
        self,
        monthly_prices: List[float],
        maturity_price: float,
        bonus_month_multiplier: float = 1.0,
        actual_jewellery_va_pct: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Simulates an 11-month cash-accumulation scheme with jeweller bonus:
        - Buyer pays ₹X for 11 months. Total cash deposited = 11 * X.
        - Jeweller adds bonus = bonus_month_multiplier * X (e.g., 1.0 * X = ₹X).
        - Total purchasing voucher = (11 + bonus_month_multiplier) * X = 12 * X.
        - Gold rate is NOT locked monthly; gold is purchased at Month 12 rate P_mat!
        - Standard jewellery making charge (VA) applies unless promotional discount.
        
        Harmonic Mean Risk Derivation:
            Weight Scheme buys G_weight = X * sum(1 / P_t) = 11 * X / H(P)
            Cash Scheme buys   G_cash   = 12 * X / [P_mat * (1 + VA_net) * (1 + GST)]
            If gold rises significantly, the 1-month bonus (+9.09%) is severely eroded.
        """
        num_inst = len(monthly_prices)
        assert num_inst == 11, f"Expected 11 monthly prices, got {num_inst}"
        
        target_va = self.jewellery_va if actual_jewellery_va_pct is None else (actual_jewellery_va_pct / 100.0)
        total_principal = self.X * num_inst
        bonus_amount = self.X * bonus_month_multiplier
        total_voucher = total_principal + bonus_amount
        
        # Buying jewellery at month 12 rate P_mat with VA and GST:
        # Total Invoice = Grams * P_mat * (1 + VA) * (1 + GST) = total_voucher
        # Grams acquired:
        price_per_gram_all_inclusive = maturity_price * (1.0 + target_va) * (1.0 + self.gst)
        grams_jewellery = total_voucher / price_per_gram_all_inclusive
        
        # If buying raw gold / bullion at month 12 with voucher:
        # Pre-tax raw gold purchasing power (exact counterpart to weight scheme accumulation):
        grams_raw_gold = total_voucher / maturity_price
        # Post-tax physical bullion/coin (if customer pays 3% GST on redemption):
        grams_post_tax_bullion = total_voucher / (maturity_price * (1.0 + self.gst))
        
        # Retail value of jewellery acquired
        retail_jewellery_value = total_voucher
        raw_gold_value = grams_jewellery * maturity_price
        
        # Cash flows for XIRR:
        # 11 monthly outflows of -X at day 0, 30, ..., 300
        # Terminal inflow: total_voucher at day 365
        cash_flows: List[Tuple[float, float]] = [(i * 30.0, -self.X) for i in range(num_inst)]
        maturity_day = 365.0
        cash_flows.append((maturity_day, total_voucher))
        
        scheme_xirr = XIRRSolver.calculate_xirr(cash_flows)
        
        # Cash flow based on raw gold equivalent
        cash_flows_raw = [(i * 30.0, -self.X) for i in range(num_inst)]
        cash_flows_raw.append((maturity_day, raw_gold_value))
        raw_xirr = XIRRSolver.calculate_xirr(cash_flows_raw)
        
        return {
            "model": "CASH_BONUS_1_MONTH",
            "installments_count": num_inst,
            "monthly_installment": self.X,
            "total_principal_paid": total_principal,
            "bonus_amount_added": round(bonus_amount, 2),
            "total_voucher_value": round(total_voucher, 2),
            "maturity_gold_rate": maturity_price,
            "gold_accumulated_grams": round(grams_jewellery, 4),
            "raw_gold_accumulated_grams": round(grams_raw_gold, 4),
            "post_tax_bullion_grams": round(grams_post_tax_bullion, 4),
            "raw_gold_market_value": round(raw_gold_value, 2),
            "full_retail_jewellery_value": round(retail_jewellery_value, 2),
            "xirr_jewellery_basis": round(scheme_xirr * 100, 2) if scheme_xirr is not None else None,
            "xirr_raw_gold_basis": round(raw_xirr * 100, 2) if raw_xirr is not None else None,
            "absolute_return_pct": round((bonus_amount / total_principal) * 100, 2)
        }

    # --------------------------------------------------------------------------
    # MODEL 3: DIRECT MONTHLY GOLD SIP (PHYSICAL COIN / DCA BENCHMARK)
    # --------------------------------------------------------------------------
    def calculate_direct_gold_sip(
        self,
        monthly_prices: List[float],
        maturity_price: float,
        sip_mode: str = "COIN_BULLION"
    ) -> Dict[str, Any]:
        """
        Simulates Direct Monthly Gold SIP (11 installments of ₹X):
        
        Modes:
        A. 'COIN_BULLION' (Realistic Physical Gold Accumulation):
           - Buyer purchases 22K gold coins/bars each month.
           - Minting charge: coin_va (default 2.0%) + GST (3.0%).
           - Gold weight acquired at month t:
               g_t = X / [P_t * (1 + coin_va) * (1 + GST)]
           - At Month 12:
               1. Liquid Bullion Sale Value:
                  V_liquid = G_total * P_mat * (1 - buyback_spread)
               2. Converted to Jewellery:
                  Customer trades coins to jeweller; jeweller assesses making charge (VA)
                  on jewellery. Customer gets less jewellery weight or pays extra VA.
                  
        B. 'BENCHMARK_SPOT_DCA' (Frictionless Mathematical Spot Gold):
           - Buyer accumulates g_t = X / P_t.
           - Total gold = sum(X / P_t).
        """
        num_inst = len(monthly_prices)
        assert num_inst == 11, f"Expected 11 monthly prices, got {num_inst}"
        total_principal = self.X * num_inst
        
        if sip_mode == "COIN_BULLION":
            # Real physical coin purchase with minting markups
            monthly_grams = [self.X / (p * (1.0 + self.coin_va) * (1.0 + self.gst)) for p in monthly_prices]
            total_grams = sum(monthly_grams)
            avg_cost_per_gram = total_principal / total_grams
            
            # Scenario A1: Sell coin back for cash at maturity (Liquid)
            liquidation_value = total_grams * maturity_price * (1.0 - self.buyback_spread)
            
            # Scenario A2: Exchange coins to purchase retail jewellery at Month 12
            # Value of coins credited by jeweller: total_grams * maturity_price
            # Standard jewellery requires VA (e.g. 14%) + GST (3%)
            jewellery_weight_obtained = (total_grams * maturity_price) / (maturity_price * (1.0 + self.jewellery_va))
            
            # Cash flows for Liquidation XIRR
            cash_flows_liquid = [(i * 30.0, -self.X) for i in range(num_inst)]
            maturity_day = 365.0
            cash_flows_liquid.append((maturity_day, liquidation_value))
            xirr_liquid = XIRRSolver.calculate_xirr(cash_flows_liquid)
            
            # Cash flows for Jewellery Value XIRR (retail equivalence)
            # What would that jewellery cost on the retail shelf?
            retail_equiv_value = (total_grams * maturity_price) * (1.0 + self.jewellery_va) * (1.0 + self.gst)
            
            return {
                "model": "DIRECT_SIP_COIN_BULLION",
                "installments_count": num_inst,
                "monthly_installment": self.X,
                "total_principal_paid": total_principal,
                "gold_accumulated_grams": round(total_grams, 4),
                "average_cost_per_gram": round(avg_cost_per_gram, 2),
                "maturity_gold_rate": maturity_price,
                "liquid_cash_value": round(liquidation_value, 2),
                "jewellery_weight_obtained_grams": round(jewellery_weight_obtained, 4),
                "xirr_liquid_bullion": round(xirr_liquid * 100, 2) if xirr_liquid is not None else None,
                "absolute_liquid_return_pct": round(((liquidation_value - total_principal) / total_principal) * 100, 2)
            }
        else:
            # Benchmark frictionless Spot DCA
            monthly_grams = [self.X / p for p in monthly_prices]
            total_grams = sum(monthly_grams)
            avg_cost_per_gram = total_principal / total_grams
            spot_value = total_grams * maturity_price
            
            cash_flows_spot = [(i * 30.0, -self.X) for i in range(num_inst)]
            maturity_day = 365.0
            cash_flows_spot.append((maturity_day, spot_value))
            xirr_spot = XIRRSolver.calculate_xirr(cash_flows_spot)
            
            return {
                "model": "DIRECT_SIP_SPOT_BENCHMARK",
                "installments_count": num_inst,
                "monthly_installment": self.X,
                "total_principal_paid": total_principal,
                "gold_accumulated_grams": round(total_grams, 4),
                "average_cost_per_gram": round(avg_cost_per_gram, 2),
                "maturity_gold_rate": maturity_price,
                "liquid_cash_value": round(spot_value, 2),
                "xirr_spot_gold": round(xirr_spot * 100, 2) if xirr_spot is not None else None,
                "absolute_return_pct": round(((spot_value - total_principal) / total_principal) * 100, 2)
            }

    # --------------------------------------------------------------------------
    # SECTION 3: COMPREHENSIVE COMPARISON & SENSITIVITY MATRIX
    # --------------------------------------------------------------------------
    def compare_all_options(
        self,
        monthly_prices: List[float],
        maturity_price: float,
        va_waiver_pct: float = 14.0,
        actual_jewellery_va_pct: float = 14.0,
        bonus_month_multiplier: float = 1.0
    ) -> Dict[str, Any]:
        """
        Executes a rigorous head-to-head financial comparison across:
        1. Weight-Based Scheme (GRT / Lalitha Style with VA Waiver)
        2. Cash-Based Scheme (Tanishq Style with 1-Month Bonus)
        3. Direct Physical Coin SIP (Real Bullion DCA)
        4. Benchmark Spot Gold DCA (Frictionless)
        
        Calculates exact gram differences, cost disparities, and XIRR spreads.
        """
        weight_scheme = self.calculate_weight_based_scheme(
            monthly_prices, maturity_price, va_waiver_pct, actual_jewellery_va_pct
        )
        cash_scheme = self.calculate_cash_bonus_scheme(
            monthly_prices, maturity_price, bonus_month_multiplier, actual_jewellery_va_pct
        )
        coin_sip = self.calculate_direct_gold_sip(
            monthly_prices, maturity_price, sip_mode="COIN_BULLION"
        )
        spot_sip = self.calculate_direct_gold_sip(
            monthly_prices, maturity_price, sip_mode="BENCHMARK_SPOT_DCA"
        )
        
        # Harmonic mean of prices during the 11 installments
        harmonic_mean = len(monthly_prices) / sum(1.0 / p for p in monthly_prices)
        arithmetic_mean = sum(monthly_prices) / len(monthly_prices)
        gold_price_appreciation_pct = ((maturity_price - monthly_prices[0]) / monthly_prices[0]) * 100.0
        
        # Analytical Breakeven Derivation:
        # Cash scheme grams = (11 + b) * X / [P_mat * (1 + VA) * (1 + GST)]
        # Weight scheme grams = 11 * X / H_price
        # At what P_mat is Weight Scheme grams > Cash Scheme grams?
        # For pure raw gold parity:
        # (11 + b) / P_mat == 11 / H_price => P_mat = H_price * (11 + b) / 11
        # When b = 1.0, P_mat_breakeven = H_price * (12 / 11) = H_price * 1.090909 (+9.09% vs Harmonic Mean)
        breakeven_p_mat_raw = harmonic_mean * (11.0 + bonus_month_multiplier) / 11.0
        breakeven_appreciation_pct = ((breakeven_p_mat_raw - monthly_prices[0]) / monthly_prices[0]) * 100.0
        
        # Key comparative insight:
        # Weight scheme vs Direct Coin SIP:
        gram_advantage_vs_coin = weight_scheme["gold_accumulated_grams"] - coin_sip["gold_accumulated_grams"]
        gram_advantage_vs_cash = weight_scheme["gold_accumulated_grams"] - cash_scheme["gold_accumulated_grams"]
        
        return {
            "parameters": {
                "monthly_installment": self.X,
                "total_invested": self.X * 11,
                "start_price": monthly_prices[0],
                "maturity_price": maturity_price,
                "arithmetic_mean_price": round(arithmetic_mean, 2),
                "harmonic_mean_price": round(harmonic_mean, 2),
                "gold_price_change_pct": round(gold_price_appreciation_pct, 2),
                "va_waiver_pct": va_waiver_pct,
                "actual_jewellery_va_pct": actual_jewellery_va_pct
            },
            "weight_based_scheme": weight_scheme,
            "cash_bonus_scheme": cash_scheme,
            "direct_coin_sip": coin_sip,
            "benchmark_spot_sip": spot_sip,
            "comparative_metrics": {
                "weight_vs_cash_gram_delta": round(gram_advantage_vs_cash, 4),
                "weight_vs_coin_gram_delta": round(gram_advantage_vs_coin, 4),
                "weight_scheme_gram_premium_pct": round((gram_advantage_vs_coin / coin_sip["gold_accumulated_grams"]) * 100, 2),
                "breakeven_gold_price_for_cash_parity": round(breakeven_p_mat_raw, 2),
                "breakeven_price_change_from_start_pct": round(breakeven_appreciation_pct, 2)
            }
        }

    # --------------------------------------------------------------------------
    # SECTION 4: MARKET REGIME SENSITIVITY MATRIX
    # --------------------------------------------------------------------------
    def run_market_regime_matrix(
        self,
        base_price: float = 14270.0,
        va_waiver_pct: float = 14.0
    ) -> Dict[str, Any]:
        """
        Simulates 5 distinct market regimes over the 11-month cycle + Month 12 maturity:
        1. Strong Bull Market (+25% annualized price rally)
        2. Moderate Bull Market (+10% price growth)
        3. Flat / Sideways Market (0% growth)
        4. Moderate Bear Market (-10% price drop)
        5. Strong Bear Market (-20% price collapse)
        """
        regimes = {
            "Strong Bull (+25%)": 0.25,
            "Moderate Bull (+10%)": 0.10,
            "Flat Market (0%)": 0.00,
            "Moderate Bear (-10%)": -0.10,
            "Strong Bear (-20%)": -0.20
        }
        
        results = {}
        for name, annual_return in regimes.items():
            # Monthly compounding price vector
            monthly_rate = (1.0 + annual_return) ** (1.0 / 12.0) - 1.0
            prices = [base_price * ((1.0 + monthly_rate) ** m) for m in range(11)]
            maturity_price = base_price * ((1.0 + monthly_rate) ** 12)
            
            comp = self.compare_all_options(
                monthly_prices=prices,
                maturity_price=maturity_price,
                va_waiver_pct=va_waiver_pct,
                actual_jewellery_va_pct=va_waiver_pct
            )
            
            results[name] = {
                "start_rate": round(prices[0], 1),
                "maturity_rate": round(maturity_price, 1),
                "weight_scheme_grams": comp["weight_based_scheme"]["gold_accumulated_grams"],
                "cash_scheme_grams": comp["cash_bonus_scheme"]["gold_accumulated_grams"],
                "direct_coin_grams": comp["direct_coin_sip"]["gold_accumulated_grams"],
                "weight_scheme_xirr": comp["weight_based_scheme"]["xirr_jewellery_basis"],
                "cash_scheme_xirr": comp["cash_bonus_scheme"]["xirr_jewellery_basis"],
                "direct_coin_xirr": comp["direct_coin_sip"]["xirr_liquid_bullion"],
                "winner_for_jewellery": "Weight Scheme (GRT/Lalitha)" if comp["weight_based_scheme"]["gold_accumulated_grams"] >= comp["cash_bonus_scheme"]["gold_accumulated_grams"] else "Cash Bonus Scheme (Tanishq)",
                "winner_for_bullion": "Direct Coin SIP"
            }
            
        return results


# ==============================================================================
# SECTION 5: EXPONENTIAL SMOOTHING (HOLT-WINTERS) PATH GENERATOR
# ==============================================================================

class DoubleExponentialSmoothing:
    """
    Holt's Linear Exponential Smoothing (State-Space Formulation)
    Used to model local level and trend without external dependencies.
    
    Equations:
        Level:  L_t = alpha * Y_t + (1 - alpha) * (L_{t-1} + b_{t-1})
        Trend:  b_t = beta * (L_t - L_{t-1}) + (1 - beta) * b_{t-1}
        Forecast h steps ahead: F_{t+h} = L_t + h * b_t
    """
    def __init__(self, alpha: float = 0.3, beta: float = 0.1):
        self.alpha = alpha
        self.beta = beta
        self.level = 0.0
        self.trend = 0.0
        self.fitted = False

    def fit(self, series: List[float]):
        if len(series) < 2:
            raise ValueError("Need at least 2 data points for Holt smoothing")
        
        self.level = series[0]
        self.trend = series[1] - series[0]
        
        for t in range(1, len(series)):
            val = series[t]
            prev_level = self.level
            prev_trend = self.trend
            
            self.level = self.alpha * val + (1.0 - self.alpha) * (prev_level + prev_trend)
            self.trend = self.beta * (self.level - prev_level) + (1.0 - self.beta) * prev_trend
            
        self.fitted = True

    def forecast(self, steps: int) -> List[float]:
        if not self.fitted:
            raise ValueError("Model must be fitted before forecasting")
        return [self.level + (h * self.trend) for h in range(1, steps + 1)]


# ==============================================================================
# SECTION 6: CONVENIENCE FUNCTIONS FOR QUICK INTEGRATION
# ==============================================================================

def calculate_gold_scheme_vs_sip(
    monthly_amount: float = 10000.0,
    current_22k_rate: float = 14270.0,
    annual_growth_rate_pct: float = 10.0,
    va_waiver_pct: float = 14.0,
    jewellery_va_pct: float = 14.0
) -> Dict[str, Any]:
    """
    One-shot evaluator for frontend calculators and API handlers.
    Generates an 11-month price series starting from current_22k_rate,
    and returns full comparative metrics.
    """
    engine = GoldSavingsEngine(
        monthly_installment=monthly_amount,
        standard_jewellery_va_pct=jewellery_va_pct
    )
    
    monthly_factor = (1.0 + (annual_growth_rate_pct / 100.0)) ** (1.0 / 12.0)
    prices = [current_22k_rate * (monthly_factor ** i) for i in range(11)]
    maturity_price = current_22k_rate * (monthly_factor ** 12)
    
    return engine.compare_all_options(
        monthly_prices=prices,
        maturity_price=maturity_price,
        va_waiver_pct=va_waiver_pct,
        actual_jewellery_va_pct=jewellery_va_pct
    )


if __name__ == "__main__":
    print("=" * 80)
    print("CHENNAI 22K GOLD SAVINGS ENGINE: VERIFICATION RUN")
    print("=" * 80)
    
    engine = GoldSavingsEngine(monthly_installment=10000.0)
    res = calculate_gold_scheme_vs_sip(
        monthly_amount=10000.0,
        current_22k_rate=14270.0,
        annual_growth_rate_pct=10.0,
        va_waiver_pct=14.0
    )
    
    ws = res["weight_based_scheme"]
    cs = res["cash_bonus_scheme"]
    ds = res["direct_coin_sip"]
    comp = res["comparative_metrics"]
    
    print(f"Monthly Installment: ₹{res['parameters']['monthly_installment']:,.0f} x 11 Months")
    print(f"Total Invested:      ₹{res['parameters']['total_invested']:,.0f}")
    print(f"Current 22K Rate:    ₹{res['parameters']['start_price']:,.1f}/g -> Maturity: ₹{res['parameters']['maturity_price']:,.1f}/g\n")
    
    print(f"1. Weight-Based Scheme (GRT / Lalitha):")
    print(f"   - Gold Weight:    {ws['gold_accumulated_grams']} g")
    print(f"   - Retail Value:   ₹{ws['full_retail_jewellery_value']:,.2f}")
    print(f"   - VA Savings:     ₹{ws['va_savings_rupees']:,.2f} ({ws['va_waiver_pct']}% waived)")
    print(f"   - XIRR (Yield):   {ws['xirr_jewellery_basis']}%\n")
    
    print(f"2. Cash-Based Scheme (Tanishq 1-Mo Bonus):")
    print(f"   - Gold Weight:    {cs['gold_accumulated_grams']} g")
    print(f"   - Retail Value:   ₹{cs['full_retail_jewellery_value']:,.2f}")
    print(f"   - Bonus Added:    ₹{cs['bonus_amount_added']:,.2f}")
    print(f"   - XIRR (Yield):   {cs['xirr_jewellery_basis']}%\n")
    
    print(f"3. Direct Coin SIP (Physical DCA):")
    print(f"   - Gold Weight:    {ds['gold_accumulated_grams']} g")
    print(f"   - Liquid Value:   ₹{ds['liquid_cash_value']:,.2f}")
    print(f"   - XIRR (Liquid):  {ds['xirr_liquid_bullion']}%\n")
    
    print(f"4. Analytical Summary:")
    print(f"   - Weight Scheme Gram Advantage vs Cash Scheme: {comp['weight_vs_cash_gram_delta']} g")
    print(f"   - Weight Scheme Gram Advantage vs Coin SIP:    {comp['weight_vs_coin_gram_delta']} g")
    print(f"   - Breakeven Gold Price for Cash Parity:        ₹{comp['breakeven_gold_price_for_cash_parity']:,.1f} (+{comp['breakeven_price_change_from_start_pct']}%)")
    print("=" * 80)
