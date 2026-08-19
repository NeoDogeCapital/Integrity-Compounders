"""
fiscal_trailing_apply.py — apply Fiscal.ai trailing fundamentals to the model

The Fiscal MCP is session-bound (Claude's OAuth), so the sweep itself happens
in-session: Claude batches codemode.company_ratios(periodType="latest") across
the active universe and saves the merged result as a JSON snapshot. This script
is the deterministic half — it takes that snapshot and applies it.

Why this exists (2026-08-18): cmd's trailing fundamentals had two defects.
(1) roic_trailing was only ever written by data_updater's yfinance path, which
stores returnOnEquity ×100 as a "ROIC proxy" — MA showed 241%, STX 372% — and
that fed the factor scorer's Quality factor and the P1 pillar context directly.
(2) The same columns were written at decimal scale by the CSV signal loader and
percent scale by the yfinance path, so scales varied by row. Fiscal's
standardized calcs (true NOPAT/invested-capital ROIC, native gross/FCF margin)
replace both. See CLAUDE.md §13 — the gross-margin and FCF-margin proxies are
retired for any name this script covers.

Canonical units after apply (matching engines/screener.py thresholds and the
majority convention): margins / yields / CAGRs in PLAIN PERCENT on cmd, except
eps_cagr_1y, gp_cagr_1y, gp_cagr_3y, capex_to_rev, sbc_pct_revenue and
fcf_ev_yield which stay DECIMAL (contamination-detector and QGS convention).
enterprise_value / market_cap in raw dollars. trailing_source records lineage.

Recomputed downstream, same formulas as data_updater.load_fiscal_csv_signals:
  fcf_ev_yield = calculated_fcf / calculated_tev
  QGS   = (fwd_rev + fwd_eps) × fcf_ev × roic × fcf_margin   (decimals; fwd
          taken from ic_signal_rankings' latest rank_date — the CSV-loaded
          decimals, NOT cmd's yfinance-scale fwd columns)
  GER   = (fwd_rev + fwd_eps) / max(sbc_pct + shares_growth, 0.01) — sbc_pct is
          now TRUE SBC/revenue (Fiscal) instead of the old SBC/EV proxy
  earnings_quality_flag — recomputed only when Fiscal supplies eps 1y AND 3y
          and gp 1y (gp_cagr_3y keeps its CSV value; Fiscal's LTM view lacks it)
  Six V12 quality indicators + profile + legacy gate_* aliases
  fcf_ev_rank percentile re-ranked universe-wide

Usage:
    python scripts/fiscal_trailing_apply.py data/snapshots/fiscal_trailing_2026-08-18.json
    python scripts/fiscal_trailing_apply.py <snapshot.json> --dry-run
"""
import sys
import json
import argparse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg2
from config.settings import settings

QGS_TIERS = [(0.0028, 'RARE_ELITE'), (0.0016, 'EXCEPTIONAL'),
             (0.0006, 'GOOD_COMPOUNDER'), (0.0002, 'AVERAGE')]

# indicator: (sweep-derived percent value key, op, threshold, legacy gate col)
INDICATORS = [
    ("capital_efficiency",     "roic_pct",       ">=", 10.0, "gate_quality"),
    ("pricing_power",          "gross_pct",      ">=", 30.0, "gate_pricing_power"),
    ("operational_efficiency", "op_pct",         ">=", 15.0, "gate_durability"),
    ("cash_conversion",        "fcf_margin_pct", ">=",  7.0, "gate_cash_conv"),
    ("growth_durability",      "rev3y_pct",      ">=",  5.0, "gate_reinvestment"),
    ("balance_sheet",          "nd_ebitda",      "<=",  3.0, "gate_balance_sheet"),
]

BEFORE_COLS = ["roic_trailing", "gross_margin_trailing", "fcf_margin_trailing",
               "op_margin", "fcf_yield_current", "net_debt_ebitda",
               "revenue_3y_cagr_trailing", "eps_3y_cagr_trailing", "buyback_yield",
               "capex_to_rev", "sbc_pct_revenue", "fcf_ev_yield",
               "quality_growth_score", "qgs_tier", "growth_efficiency_ratio",
               "ger_flag", "indicators_pass", "quality_profile",
               "earnings_quality_flag", "eps_cagr_1y", "gp_cagr_1y", "gp_cagr_3y"]


def qgs_tier_of(qgs):
    for lo, tier in QGS_TIERS:
        if qgs > lo:
            return tier
    return 'LOW_QUALITY'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", help="merged sweep JSON (ticker -> metrics)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sweep = json.loads(Path(a.snapshot).read_text())
    asof = sweep.pop("_asof", str(date.today()))
    covered = {t: m for t, m in sweep.items() if m}
    missing = sorted(t for t, m in sweep.items() if not m)
    print(f"  snapshot: {len(covered)} names with data, {len(missing)} unresolved"
          + (f" ({', '.join(missing[:10])}{'…' if len(missing) > 10 else ''})" if missing else ""))

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("ALTER TABLE company_market_data ADD COLUMN IF NOT EXISTS trailing_source TEXT")

    # before-state for the diff
    cur.execute(f"""SELECT ticker, data_date, {', '.join(BEFORE_COLS)}
        FROM company_market_data cmd
        WHERE data_date = (SELECT MAX(data_date) FROM company_market_data WHERE ticker=cmd.ticker)
          AND ticker = ANY(%s)""", (list(covered),))
    before = {r[0]: dict(zip(["data_date"] + BEFORE_COLS,
                             [str(r[1])] + [float(x) if isinstance(x, (int, float)) or
                                            hasattr(x, 'quantize') else x for x in r[2:]]))
              for r in cur.fetchall()}
    before_path = ROOT / "data" / "snapshots" / f"fiscal_apply_before_{asof}.json"
    if not a.dry_run:
        before_path.write_text(json.dumps(before, default=str))

    # forward decimals from the CSV-loaded rankings (NOT cmd's yfinance columns)
    cur.execute("""SELECT ticker, fwd_rev_3y_cagr, fwd_eps_3y_cagr FROM ic_signal_rankings
        WHERE rank_date = (SELECT MAX(rank_date) FROM ic_signal_rankings)""")
    fwd = {r[0]: (float(r[1]) if r[1] is not None else None,
                  float(r[2]) if r[2] is not None else None) for r in cur.fetchall()}

    fcf_ev_all = {}
    applied = 0
    for tk, m in covered.items():
        if tk not in before:
            continue
        g = lambda k: m.get(k)
        pct = lambda v: round(v * 100, 2) if v is not None else None

        roic, gm, om = g("ratio_return_on_invested_capital"), g("ratio_gross_profit_margin"), g("ratio_operating_margin")
        fcfm, fy, nde = g("ratio_fcf_margin"), g("ratio_fcf_yield"), g("ratio_net_debt_to_ebitda")
        rev3, eps3, eps1 = g("growth_revenue_3y_cagr"), g("growth_diluted_eps_3y_cagr"), g("growth_diluted_eps_1y")
        gp1, bb, capex = g("growth_gross_profit_1y"), g("ratio_buyback_yield"), g("ratio_capex_to_revenue")
        sbc, fcf, tev = g("ratio_sbc_to_revenue"), g("calculated_fcf"), g("calculated_tev")
        mcap, shr3 = g("calculated_market_cap"), g("growth_diluted_weighted_avg_shares_outstanding_3y_cagr")

        fcf_ev = (fcf / tev) if (fcf is not None and tev and tev > 0) else None
        if fcf_ev is not None:
            fcf_ev_all[tk] = fcf_ev

        fr, fe = fwd.get(tk, (None, None))
        qgs = qgs_t = None
        if None not in (fr, fe, fcf_ev, roic, fcfm) and fcf_ev > 0:
            qgs = round((fr + fe) * fcf_ev * roic * fcfm, 6)
            qgs_t = qgs_tier_of(qgs)

        ger = ger_flag = None
        if None not in (fr, fe, sbc, shr3):
            den = sbc + shr3
            if den < 0:
                ger_flag = 'NET_RETURNER'
            else:
                ger = round((fr + fe) / max(den, 0.01), 4)
                ger_flag = 'FLOORED' if den < 0.01 else 'NORMAL'

        # contamination detector: gp_cagr_3y stays CSV-sourced (decimal)
        prev = before[tk]
        gp3 = prev.get("gp_cagr_3y")
        gp3 = float(gp3) if gp3 is not None else None
        eq = eps_acc = gp_acc = None
        if None not in (eps1, eps3, gp1, gp3):
            eps_acc, gp_acc = round(eps1 - eps3, 6), round(gp1 - gp3, 6)
            eq = ('EPS_CONFIRMED' if eps_acc > 0 and gp_acc > 0 else
                  'EPS_ENGINEERED' if eps_acc > 0 else
                  'GP_LEADING' if gp_acc > 0 else 'NEUTRAL')

        vals = {"roic_pct": pct(roic), "gross_pct": pct(gm), "op_pct": pct(om),
                "fcf_margin_pct": pct(fcfm), "rev3y_pct": pct(rev3),
                "nd_ebitda": round(nde, 4) if nde is not None else None}
        gates, n_pass, fails = {}, 0, []
        for name, key, op, th, legacy in INDICATORS:
            v = vals[key]
            if v is None:
                gates[legacy] = None
            else:
                ok = v >= th if op == ">=" else v <= th
                gates[legacy] = ok
                n_pass += ok
                if not ok:
                    fails.append(name)
        profile = ("FULL_COMPOUNDER" if n_pass >= 5 else "QUALITY_WATCH" if n_pass >= 3
                   else "DEVELOPING" if n_pass >= 1 else "QUALITY_CONCERN")

        sets = {
            "roic_trailing": vals["roic_pct"], "gross_margin_trailing": vals["gross_pct"],
            "op_margin": vals["op_pct"], "fcf_margin_trailing": vals["fcf_margin_pct"],
            "fcf_yield_current": pct(fy), "net_debt_ebitda": vals["nd_ebitda"],
            "revenue_3y_cagr_trailing": vals["rev3y_pct"], "eps_3y_cagr_trailing": pct(eps3),
            "buyback_yield": pct(bb),
            "eps_cagr_1y": eps1, "gp_cagr_1y": gp1,
            "capex_to_rev": round(capex, 4) if capex is not None else None,
            "sbc_pct_revenue": round(sbc, 6) if sbc is not None else None,
            "shares_out_growth_3y_cagr": shr3,
            "enterprise_value": tev, "market_cap": mcap,
            "fcf_ev_yield": round(fcf_ev, 6) if fcf_ev is not None else None,
            "quality_growth_score": qgs, "qgs_tier": qgs_t,
            "growth_efficiency_ratio": ger, "ger_flag": ger_flag,
            "indicators_pass": n_pass, "quality_profile": profile,
            "gates_pass": n_pass, "watch_flags": json.dumps(fails),
            "trailing_source": f"fiscal_mcp:{asof}",
        }
        if eq is not None:
            sets.update({"eps_acceleration": eps_acc, "gp_acceleration": gp_acc,
                         "earnings_quality_flag": eq})
        for legacy, ok in gates.items():
            if ok is not None:
                sets[legacy] = bool(ok)
        # never null out a value Fiscal doesn't have — keep the existing one
        sets = {k: v for k, v in sets.items() if v is not None}

        cur.execute(f"""UPDATE company_market_data SET {', '.join(f'{k}=%s' for k in sets)}
            WHERE ticker=%s AND data_date=(SELECT MAX(data_date) FROM company_market_data WHERE ticker=%s)""",
                    list(sets.values()) + [tk, tk])
        cur.execute("""UPDATE companies SET quality_profile=%s, earnings_quality_flag=COALESCE(%s, earnings_quality_flag)
            WHERE ticker=%s""", (profile, eq, tk))
        if qgs is not None:
            cur.execute("""UPDATE ic_signal_rankings SET quality_growth_score=%s, qgs_tier=%s,
                fcf_ev_yield=%s, growth_efficiency_ratio=COALESCE(%s, growth_efficiency_ratio),
                ger_flag=COALESCE(%s, ger_flag)
                WHERE ticker=%s AND rank_date=(SELECT MAX(rank_date) FROM ic_signal_rankings)""",
                        (qgs, qgs_t, sets.get("fcf_ev_yield"), ger, ger_flag, tk))
        applied += 1

    # universe-wide FCF/EV percentile re-rank
    ranked = sorted(fcf_ev_all.items(), key=lambda x: x[1], reverse=True)
    n = max(len(ranked), 1)
    for i, (tk, _) in enumerate(ranked):
        p = round((1 - (i + 1) / n) * 100, 1)
        cur.execute("""UPDATE company_market_data SET fcf_ev_rank=%s WHERE ticker=%s
            AND data_date=(SELECT MAX(data_date) FROM company_market_data WHERE ticker=%s)""", (p, tk, tk))
        cur.execute("UPDATE companies SET fcf_ev_rank=%s WHERE ticker=%s", (p, tk))

    if a.dry_run:
        conn.rollback()
        print(f"  DRY RUN — would apply {applied} names (rolled back)")
    else:
        conn.commit()
        print(f"  applied {applied} names · trailing_source=fiscal_mcp:{asof}")
        print(f"  before-state: {before_path.relative_to(ROOT)}")

    # diff summary (works for dry runs too — compares in-memory)
    cur.execute(f"""SELECT ticker, qgs_tier, quality_profile, earnings_quality_flag, roic_trailing
        FROM company_market_data cmd
        WHERE data_date=(SELECT MAX(data_date) FROM company_market_data WHERE ticker=cmd.ticker)
          AND ticker = ANY(%s)""", (list(before),))
    cur2 = conn.cursor()
    cur2.execute("SELECT ticker, COALESCE(in_portfolio, FALSE) FROM companies")
    held = {r[0] for r in cur2.fetchall() if r[1]}
    changes = {"qgs_tier": [], "quality_profile": [], "earnings_quality_flag": []}
    for tk, tier, prof, eqf, roic_now in cur.fetchall():
        b = before[tk]
        for field, now in (("qgs_tier", tier), ("quality_profile", prof),
                           ("earnings_quality_flag", eqf)):
            if b.get(field) and now and b[field] != now:
                changes[field].append((tk, b[field], now, tk in held))
    print()
    for field, rows in changes.items():
        print(f"  {field}: {len(rows)} changed")
        for tk, old, new, h in sorted(rows, key=lambda r: (not r[3], r[0])):
            print(f"   {'★' if h else ' '} {tk:<6} {old} → {new}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
