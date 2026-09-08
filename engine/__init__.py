"""
Chennai 22K Gold Analytics & Savings Engine Package
"""

from .gold_scheme_calculator import (
    XIRRSolver,
    GoldSavingsEngine,
    ChennaiJewellerProfiles,
    DoubleExponentialSmoothing,
    calculate_gold_scheme_vs_sip
)

__all__ = [
    "XIRRSolver",
    "GoldSavingsEngine",
    "ChennaiJewellerProfiles",
    "DoubleExponentialSmoothing",
    "calculate_gold_scheme_vs_sip"
]
