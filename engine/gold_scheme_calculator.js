/**
 * ==============================================================================
 * CHENNAI 22K GOLD SAVINGS SCHEME (11-MONTH CHIT) VS PHYSICAL GOLD SIP ENGINE
 * ==============================================================================
 * Pure Vanilla JavaScript Implementation (Zero External Dependencies)
 * 
 * Quantitative Financial Mathematics for:
 * 1. Chennai Jeweller 11-Month Schemes:
 *    - Weight-Based DCA + Value Addition (VA / Making Charges) Waiver (GRT, Lalitha)
 *    - Cash-Based DCA + 1-Month Bonus Voucher (Tanishq Golden Harvest, Kalyan Dhanvarsha)
 * 2. Direct Monthly Gold SIP:
 *    - Physical Gold Bullion / Coin Accumulation (DCA with minting charges & GST)
 *    - Benchmark Spot DCA with Jewellery Conversion vs Liquid Bullion Holding
 * 3. High-Precision Extended Internal Rate of Return (XIRR) Engine:
 *    - Hybrid Newton-Raphson with Bracketed Bisection Fallback
 *    - Exact calendar-day discounting: (d_i - d_0) / 365.0
 * 4. Analytical Breakeven & Sensitivity Engine:
 *    - Exact harmonic mean price inflation threshold where Cash Scheme equals Weight Scheme
 *    - Comparative yield matrix across Bull, Flat, and Bear market regimes
 * ==============================================================================
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.GoldSchemeCalculator = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ============================================================================
  // SECTION 1: HIGH-PRECISION XIRR SOLVER (PURE JAVASCRIPT)
  // ============================================================================
  
  /**
   * Evaluates Net Present Value (NPV) and its derivative at rate r.
   * cashFlows: Array of { tau: number (in years), amount: number }
   */
  function npvAndDeriv(r, cashFlows) {
    if (r <= -1.0) return { npv: Infinity, deriv: Infinity };

    let npv = 0.0;
    let deriv = 0.0;
    const onePlusR = 1.0 + r;

    for (let i = 0; i < cashFlows.length; i++) {
      const { tau, amount } = cashFlows[i];
      const discount = Math.pow(onePlusR, tau);
      npv += amount / discount;
      deriv -= (tau * amount) / (discount * onePlusR);
    }

    return { npv, deriv };
  }

  /**
   * Calculates XIRR given cash flows.
   * @param {Array<{dateOrDays: Date|number, amount: number}>} cashFlows
   * @param {number} [guess=0.10]
   * @param {number} [maxIter=150]
   * @param {number} [tol=1e-8]
   * @returns {number|null} Annualized rate r or null
   */
  function calculateXIRR(cashFlows, guess = 0.10, maxIter = 150, tol = 1e-8) {
    if (!cashFlows || cashFlows.length < 2) return null;

    let hasNegative = false;
    let hasPositive = false;
    for (let i = 0; i < cashFlows.length; i++) {
      if (cashFlows[i].amount < 0) hasNegative = true;
      if (cashFlows[i].amount > 0) hasPositive = true;
    }
    if (!hasNegative || !hasPositive) return null;

    const firstEntry = cashFlows[0].dateOrDays;
    const isDate = firstEntry instanceof Date;
    const d0Time = isDate ? firstEntry.getTime() : Number(firstEntry);

    const normalized = [];
    for (let i = 0; i < cashFlows.length; i++) {
      const d = cashFlows[i].dateOrDays;
      const t = isDate ? (d.getTime() - d0Time) / (86400000 * 365.0) : (Number(d) - d0Time) / 365.0;
      normalized.push({ tau: t, amount: cashFlows[i].amount });
    }

    // Newton-Raphson
    let r = guess;
    for (let iter = 0; iter < maxIter; iter++) {
      const { npv, deriv } = npvAndDeriv(r, normalized);
      if (!isFinite(npv) || isNaN(npv)) break;
      if (Math.abs(npv) < tol) return r;
      if (Math.abs(deriv) < 1e-12) break;

      const step = npv / deriv;
      const nextR = r - step;
      if (nextR <= -0.9999) {
        r = (r - 0.9999) / 2.0;
      } else {
        r = nextR;
      }
    }

    // Bisection Fallback
    let low = -0.99;
    let high = 10.0;
    let { npv: npvLow } = npvAndDeriv(low, normalized);
    let { npv: npvHigh } = npvAndDeriv(high, normalized);

    if (npvLow * npvHigh > 0) {
      const expandedUpperBounds = [25.0, 50.0, 100.0];
      let bracketFound = false;
      for (let j = 0; j < expandedUpperBounds.length; j++) {
        high = expandedUpperBounds[j];
        const res = npvAndDeriv(high, normalized);
        npvHigh = res.npv;
        if (npvLow * npvHigh <= 0) {
          bracketFound = true;
          break;
        }
      }
      if (!bracketFound) return null;
    }

    for (let iter = 0; iter < maxIter; iter++) {
      const mid = (low + high) / 2.0;
      const { npv: npvMid } = npvAndDeriv(mid, normalized);
      if (Math.abs(npvMid) < tol || (high - low) / 2.0 < tol) {
        return mid;
      }
      if (npvLow * npvMid < 0) {
        high = mid;
        npvHigh = npvMid;
      } else {
        low = mid;
        npvLow = npvMid;
      }
    }

    return (low + high) / 2.0;
  }

  // ============================================================================
  // SECTION 2: MARQUEE CHENNAI JEWELLER PRESETS
  // ============================================================================
  const CHENNAI_JEWELLERS = {
    GRT_GOLDEN_ELEVEN: {
      name: 'GRT Jewellers - Golden Eleven',
      type: 'WEIGHT_BASED_VA_WAIVER',
      installments: 11,
      vaWaiverPct: 14.0,
      bonusMonthFraction: 0.0,
      description: 'Customer pays 11 months. Weight credited monthly. 14% VA waived at month 12.'
    },
    LALITHA_JEWELLERY: {
      name: 'Lalitha Jewellery - 11 Month Plan',
      type: 'WEIGHT_BASED_VA_WAIVER',
      installments: 11,
      vaWaiverPct: 18.0,
      bonusMonthFraction: 0.0,
      description: 'Customer pays 11 months. Weight credited monthly. Up to 18% VA waived at month 12.'
    },
    TANISHQ_GOLDEN_HARVEST: {
      name: 'Tanishq - Golden Harvest',
      type: 'CASH_BONUS_1_MONTH',
      installments: 11,
      vaWaiverPct: 0.0,
      bonusMonthFraction: 1.0,
      description: 'Customer pays 11 months. 12th month bonus installment added as purchase voucher.'
    },
    KALYAN_DHANVARSHA: {
      name: 'Kalyan Jewellers - Dhanvarsha',
      type: 'CASH_BONUS_1_MONTH',
      installments: 11,
      vaWaiverPct: 0.0,
      bonusMonthFraction: 0.85,
      description: 'Customer pays 11 months. Up to 85% bonus installment credited at maturity.'
    }
  };

  // ============================================================================
  // SECTION 3: CALCULATION ENGINES
  // ============================================================================

  /**
   * Simulates Weight-Based Scheme (e.g. GRT / Lalitha)
   */
  function calculateWeightBasedScheme({
    monthlyInstallment = 10000,
    monthlyPrices,
    maturityPrice,
    vaWaiverPct = 14.0,
    actualJewelleryVaPct = 14.0,
    gstPct = 3.0
  }) {
    const X = Number(monthlyInstallment);
    const numInst = monthlyPrices.length;
    const gst = gstPct / 100.0;
    const waiverVa = vaWaiverPct / 100.0;
    const targetVa = actualJewelleryVaPct / 100.0;

    let totalGrams = 0.0;
    for (let i = 0; i < numInst; i++) {
      totalGrams += X / monthlyPrices[i];
    }
    const totalPrincipal = X * numInst;
    const avgCostPerGram = totalPrincipal / totalGrams;

    const rawGoldValue = totalGrams * maturityPrice;
    const billedVaPct = Math.max(0.0, targetVa - waiverVa);
    const waivedVaPct = Math.min(targetVa, waiverVa);

    const fullRetailJewelleryValue = rawGoldValue * (1.0 + targetVa) * (1.0 + gst);
    const vaSavingsRupees = rawGoldValue * waivedVaPct * (1.0 + gst);
    const excessVaPayable = rawGoldValue * billedVaPct * (1.0 + gst);
    const totalOutOfPocket = totalPrincipal + excessVaPayable;

    // Cash flows for XIRR
    const cashFlows = [];
    for (let i = 0; i < numInst; i++) {
      cashFlows.push({ dateOrDays: i * 30, amount: -X });
    }
    const netTerminalValue = fullRetailJewelleryValue - excessVaPayable;
    cashFlows.push({ dateOrDays: 365, amount: netTerminalValue });

    const xirr = calculateXIRR(cashFlows);

    return {
      model: 'WEIGHT_BASED_VA_WAIVER',
      monthlyInstallment: X,
      totalPrincipalPaid: totalPrincipal,
      goldAccumulatedGrams: Number(totalGrams.toFixed(4)),
      averageCostPerGram: Number(avgCostPerGram.toFixed(2)),
      maturityGoldRate: maturityPrice,
      rawGoldMarketValue: Number(rawGoldValue.toFixed(2)),
      fullRetailJewelleryValue: Number(fullRetailJewelleryValue.toFixed(2)),
      vaWaiverPct: vaWaiverPct,
      vaSavingsRupees: Number(vaSavingsRupees.toFixed(2)),
      excessVaPayable: Number(excessVaPayable.toFixed(2)),
      totalOutOfPocket: Number(totalOutOfPocket.toFixed(2)),
      xirrJewelleryBasis: xirr !== null ? Number((xirr * 100).toFixed(2)) : null,
      absoluteReturnPct: Number((((fullRetailJewelleryValue - totalOutOfPocket) / totalOutOfPocket) * 100).toFixed(2))
    };
  }

  /**
   * Simulates Cash-Based Scheme with 1-Month Bonus (e.g. Tanishq)
   */
  function calculateCashBonusScheme({
    monthlyInstallment = 10000,
    monthlyPrices,
    maturityPrice,
    bonusMonthFraction = 1.0,
    actualJewelleryVaPct = 14.0,
    gstPct = 3.0
  }) {
    const X = Number(monthlyInstallment);
    const numInst = monthlyPrices.length;
    const gst = gstPct / 100.0;
    const targetVa = actualJewelleryVaPct / 100.0;

    const totalPrincipal = X * numInst;
    const bonusAmount = X * bonusMonthFraction;
    const totalVoucher = totalPrincipal + bonusAmount;

    // All-inclusive price per gram for jewellery at month 12
    const pricePerGramAllIn = maturityPrice * (1.0 + targetVa) * (1.0 + gst);
    const gramsJewellery = totalVoucher / pricePerGramAllIn;
    const rawGoldGrams = totalVoucher / maturityPrice;
    const postTaxBullionGrams = totalVoucher / (maturityPrice * (1.0 + gst));
    const rawGoldValue = gramsJewellery * maturityPrice;

    const cashFlows = [];
    for (let i = 0; i < numInst; i++) {
      cashFlows.push({ dateOrDays: i * 30, amount: -X });
    }
    cashFlows.push({ dateOrDays: 365, amount: totalVoucher });

    const xirr = calculateXIRR(cashFlows);

    return {
      model: 'CASH_BONUS_1_MONTH',
      monthlyInstallment: X,
      totalPrincipalPaid: totalPrincipal,
      bonusAmountAdded: Number(bonusAmount.toFixed(2)),
      totalVoucherValue: Number(totalVoucher.toFixed(2)),
      maturityGoldRate: maturityPrice,
      goldAccumulatedGrams: Number(gramsJewellery.toFixed(4)),
      rawGoldAccumulatedGrams: Number(rawGoldGrams.toFixed(4)),
      postTaxBullionGrams: Number(postTaxBullionGrams.toFixed(4)),
      rawGoldMarketValue: Number(rawGoldValue.toFixed(2)),
      fullRetailJewelleryValue: Number(totalVoucher.toFixed(2)),
      xirrJewelleryBasis: xirr !== null ? Number((xirr * 100).toFixed(2)) : null,
      absoluteReturnPct: Number(((bonusAmount / totalPrincipal) * 100).toFixed(2))
    };
  }

  /**
   * Simulates Direct Monthly Gold SIP
   */
  function calculateDirectGoldSIP({
    monthlyInstallment = 10000,
    monthlyPrices,
    maturityPrice,
    coinMakingChargePct = 2.0,
    buybackSpreadPct = 1.0,
    actualJewelleryVaPct = 14.0,
    gstPct = 3.0,
    mode = 'COIN_BULLION'
  }) {
    const X = Number(monthlyInstallment);
    const numInst = monthlyPrices.length;
    const gst = gstPct / 100.0;
    const coinVa = coinMakingChargePct / 100.0;
    const spread = buybackSpreadPct / 100.0;
    const targetVa = actualJewelleryVaPct / 100.0;
    const totalPrincipal = X * numInst;

    let totalGrams = 0.0;
    if (mode === 'COIN_BULLION') {
      for (let i = 0; i < numInst; i++) {
        totalGrams += X / (monthlyPrices[i] * (1.0 + coinVa) * (1.0 + gst));
      }
      const avgCost = totalPrincipal / totalGrams;
      const liquidationValue = totalGrams * maturityPrice * (1.0 - spread);
      const jewelleryWeightObtained = (totalGrams * maturityPrice) / (maturityPrice * (1.0 + targetVa));

      const cashFlows = [];
      for (let i = 0; i < numInst; i++) {
        cashFlows.push({ dateOrDays: i * 30, amount: -X });
      }
      cashFlows.push({ dateOrDays: 365, amount: liquidationValue });
      const xirrLiquid = calculateXIRR(cashFlows);

      return {
        model: 'DIRECT_SIP_COIN_BULLION',
        monthlyInstallment: X,
        totalPrincipalPaid: totalPrincipal,
        goldAccumulatedGrams: Number(totalGrams.toFixed(4)),
        averageCostPerGram: Number(avgCost.toFixed(2)),
        maturityGoldRate: maturityPrice,
        liquidCashValue: Number(liquidationValue.toFixed(2)),
        jewelleryWeightObtainedGrams: Number(jewelleryWeightObtained.toFixed(4)),
        xirrLiquidBullion: xirrLiquid !== null ? Number((xirrLiquid * 100).toFixed(2)) : null,
        absoluteLiquidReturnPct: Number((((liquidationValue - totalPrincipal) / totalPrincipal) * 100).toFixed(2))
      };
    } else {
      // Pure Spot Benchmark
      for (let i = 0; i < numInst; i++) {
        totalGrams += X / monthlyPrices[i];
      }
      const avgCost = totalPrincipal / totalGrams;
      const spotValue = totalGrams * maturityPrice;

      const cashFlows = [];
      for (let i = 0; i < numInst; i++) {
        cashFlows.push({ dateOrDays: i * 30, amount: -X });
      }
      cashFlows.push({ dateOrDays: 365, amount: spotValue });
      const xirrSpot = calculateXIRR(cashFlows);

      return {
        model: 'DIRECT_SIP_SPOT_BENCHMARK',
        monthlyInstallment: X,
        totalPrincipalPaid: totalPrincipal,
        goldAccumulatedGrams: Number(totalGrams.toFixed(4)),
        averageCostPerGram: Number(avgCost.toFixed(2)),
        maturityGoldRate: maturityPrice,
        liquidCashValue: Number(spotValue.toFixed(2)),
        xirrSpotGold: xirrSpot !== null ? Number((xirrSpot * 100).toFixed(2)) : null,
        absoluteReturnPct: Number((((spotValue - totalPrincipal) / totalPrincipal) * 100).toFixed(2))
      };
    }
  }

  /**
   * Head-to-head comparison across all options
   */
  function compareAllOptions({
    monthlyInstallment = 10000,
    monthlyPrices,
    maturityPrice,
    vaWaiverPct = 14.0,
    actualJewelleryVaPct = 14.0,
    bonusMonthFraction = 1.0,
    gstPct = 3.0
  }) {
    const weightScheme = calculateWeightBasedScheme({
      monthlyInstallment,
      monthlyPrices,
      maturityPrice,
      vaWaiverPct,
      actualJewelleryVaPct,
      gstPct
    });

    const cashScheme = calculateCashBonusScheme({
      monthlyInstallment,
      monthlyPrices,
      maturityPrice,
      bonusMonthFraction,
      actualJewelleryVaPct,
      gstPct
    });

    const coinSIP = calculateDirectGoldSIP({
      monthlyInstallment,
      monthlyPrices,
      maturityPrice,
      actualJewelleryVaPct,
      gstPct,
      mode: 'COIN_BULLION'
    });

    const spotSIP = calculateDirectGoldSIP({
      monthlyInstallment,
      monthlyPrices,
      maturityPrice,
      gstPct,
      mode: 'BENCHMARK_SPOT_DCA'
    });

    let invSum = 0.0;
    for (let i = 0; i < monthlyPrices.length; i++) {
      invSum += 1.0 / monthlyPrices[i];
    }
    const harmonicMean = monthlyPrices.length / invSum;
    const startPrice = monthlyPrices[0];
    const goldAppreciationPct = ((maturityPrice - startPrice) / startPrice) * 100.0;

    // Harmonic mean breakeven formula: P_mat = H * (11 + b) / 11
    const breakevenPrice = harmonicMean * (11.0 + bonusMonthFraction) / 11.0;
    const breakevenPct = ((breakevenPrice - startPrice) / startPrice) * 100.0;

    const deltaVsCash = weightScheme.goldAccumulatedGrams - cashScheme.goldAccumulatedGrams;
    const deltaVsCoin = weightScheme.goldAccumulatedGrams - coinSIP.goldAccumulatedGrams;

    return {
      parameters: {
        monthlyInstallment,
        totalInvested: monthlyInstallment * 11,
        startPrice,
        maturityPrice,
        harmonicMeanPrice: Number(harmonicMean.toFixed(2)),
        goldPriceChangePct: Number(goldAppreciationPct.toFixed(2)),
        vaWaiverPct,
        actualJewelleryVaPct
      },
      weightBasedScheme: weightScheme,
      cashBonusScheme: cashScheme,
      directCoinSIP: coinSIP,
      benchmarkSpotSIP: spotSIP,
      comparativeMetrics: {
        weightVsCashGramDelta: Number(deltaVsCash.toFixed(4)),
        weightVsCoinGramDelta: Number(deltaVsCoin.toFixed(4)),
        weightSchemeGramPremiumPct: Number(((deltaVsCoin / coinSIP.goldAccumulatedGrams) * 100).toFixed(2)),
        breakevenGoldPriceForCashParity: Number(breakevenPrice.toFixed(2)),
        breakevenPriceChangeFromStartPct: Number(breakevenPct.toFixed(2))
      }
    };
  }

  /**
   * One-click simulation helper for UI calculators
   */
  function quickEvaluate({
    monthlyAmount = 10000,
    currentRate22k = 14270,
    annualGrowthPct = 10,
    vaWaiverPct = 14
  }) {
    const monthlyFactor = Math.pow(1.0 + annualGrowthPct / 100.0, 1.0 / 12.0);
    const monthlyPrices = [];
    for (let i = 0; i < 11; i++) {
      monthlyPrices.push(currentRate22k * Math.pow(monthlyFactor, i));
    }
    const maturityPrice = currentRate22k * Math.pow(monthlyFactor, 12);

    return compareAllOptions({
      monthlyInstallment: monthlyAmount,
      monthlyPrices,
      maturityPrice,
      vaWaiverPct,
      actualJewelleryVaPct: vaWaiverPct
    });
  }

  return {
    calculateXIRR,
    calculateWeightBasedScheme,
    calculateCashBonusScheme,
    calculateDirectGoldSIP,
    compareAllOptions,
    quickEvaluate,
    CHENNAI_JEWELLERS
  };
}));
