"""
quality_indicators.py — V12 canonical name for the diagnostic Quality Indicators.

The implementation lives in engines/screener.py (kept in place to avoid churning
the many import sites). This module re-exports the public API under the V12 name:

    from engines.quality_indicators import run_indicators, INDICATORS, QUALITY_PROFILE
"""

from engines.screener import (  # noqa: F401
    INDICATORS,
    LEGACY_GATE_ALIASES,
    QUALITY_PROFILE,
    GATES,
    EPS_CAGR_CAP,
    run_gates as run_indicators,
    run_gates,
    update_universe_status,
    screen_summary,
    print_screen_summary,
    _quality_profile,
)
