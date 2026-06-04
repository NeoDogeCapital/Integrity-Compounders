# REBALANCE REPORT INSTRUCTIONS
## Integrity Compounders v9 · Monthly Pitch Book Generator
## Place this file at: integrity_compounders/REBALANCE_INSTRUCTIONS.md

---

## WHAT THIS IS

When Niko provides a list of current holdings (tickers, prices, scenario math),
Claude Code reads this file and generates a complete monthly rebalance pitch book
as a formatted HTML document matching the template below.

**Trigger phrase:** "Generate the monthly rebalance report" or "Build the pitch book"

---

## STEP 1 — WHAT NIKO WILL PROVIDE

Niko will supply one of the following:
- A list of tickers with current prices and any scenario targets
- A CSV or text file dropped into data/raw/ named like: 2026-06-01_holdings.csv
- A message listing holdings directly in Claude Code chat

If data is missing for any holding (e.g. no scenario targets provided),
pull the name's current data from universe.db and compute scenarios
using the v9 quadrant-conditional multipliers (see Section 6 below).

---

## STEP 2 — REPORT STRUCTURE (ALWAYS IN THIS ORDER)

### PAGE 1 — COVER
- Title: "[Month Year] Rebalance · Compounders v9 · Internal"
- Subtitle: "Integrity Wealth Partners · Equity Research"
- Report name: "Integrity Compounders v9 · Pitch Book"
- Subheader: "[Month Year] Rebalance"
- Description: "Portfolio Construction Memo and Per-Holding Pitches"
- Volume note: "25 holdings at 4% equal weight. Macro positioning: [Niko to confirm]. Investment Committee meeting date: [date]"
- Contents list:
  1. Portfolio Construction Memo and Factor Analysis
  2. [N] Two-Page Pitches — one per holding

---

### PAGE 2 — PORTFOLIO CONSTRUCTION MEMO

Pull all data from universe.db for current holdings.
Generate each section in this exact order:

#### 2.1 OPENING NARRATIVE
One paragraph describing the overall character of the portfolio this month.
Format: "This rebalance [describe changes]. The portfolio's overall character is best described as [characterization]."

#### 2.2 QUADRANT DISTRIBUTION TABLE
| Quadrant | Count | Weight | Names |
List all four quads + Discretionary (off-screen) row if applicable.
After table: one paragraph reading the distribution — what it means, which names to watch.

#### 2.3 STOCK-QUAD MAP
Describe notable positions on the X/Y plane:
- Most extreme Q1 position (both axes strongly positive)
- Most extreme Q2 position (highest earnings momentum, steepest multiple compression)
- Any Q4 names with migration warning to Q3
- Names clustered near the origin (borderline, one quarter could flip them)
- Any clipped outliers (values beyond ±30% X or ±5% Y)
Note: "Triangle markers indicate chart edge clipped a value."

#### 2.4 SECTOR DISTRIBUTION TABLE
| Sector | Weight | vs 28% Cap | Holdings |
Flag any sector exceeding 28% with "OVER (+Xpp)" in red.
After table: compliance flag paragraph if any sector is over cap.
Three remediation options if over cap.

#### 2.5 POD DISTRIBUTION TABLE
Two tables:
A) Pod | Count | Wt | Role | Holdings
   (count every pod each holding qualifies for, not just waterfall assignment)
B) # Pods | # Names | Wt | Holdings (labeled by factor richness)

After tables: bullet-point reading of each pod:
- What dominates and why that's intentional
- What's light and whether that's a risk
- Pod-count observations (zero-pod names, max-pod names, average)

#### 2.6 AGGREGATE STATISTICS TABLE
Three sub-tables:

**Growth & Quality:**
| Metric | Trailing 3Y | Forward 2Y | Acceleration/Note |
Revenue CAGR, EPS CAGR (capped at 25%), EPS CAGR (raw), Earnings Mom ROC

**Quality Metrics:**
| Metric | Weighted Avg | Read |
ROIC, Operating Margin, Beta, Avg Pod Count

**Valuation & Capital Return:**
| Metric | Weighted Avg | Read |
Current FCF Yield, Forward FCF Yield, Multiple ROC, Implied P/FCF, PEG, Capital Return (annual), Capital Return (18-mo cumulative)

**Risk & Return:**
| Metric | Weighted Avg | Read |
Alignment Score, Bull TR, Base TR, Bear TR, PW ETR, TR Standard Deviation, Risk-Adjusted ETR

After tables: 5-6 bullet reading of aggregates covering:
growth profile, quality, valuation concern, capital return note,
risk-return profile, earnings momentum direction.

#### 2.7 SLEEVE ASSIGNMENT TABLE
| Sleeve | Target | Actual | Notes |
Four sleeves: Core Compounders 45% / Catalyst Momentum 30% / Relative Value Pairs 15% / High-Conviction Speculative 10%
Note any zero-allocation sleeves and whether that's appropriate.

---

### PAGE 3 — HOLDINGS MASTER TABLE

Title: "Holdings Master Table · Factor Snapshot"
Subtitle: "All [N] holdings ranked by Risk-Adjusted Expected Total Return."

Columns: Tkr | Quad | Score | Signal | β | ROIC | Bull | Base | Bear | PW ETR | Risk-Adj | Setup

Color-code rows by quadrant (Q1=blue, Q2=green, Q3=red, Q4=orange).
Sort: descending by Risk-Adj.

After table:
- **Top of Book** section: describe top 4-5 names by Risk-Adj with one-sentence thesis each
- **Bottom of Book** section: describe bottom 3-4 names with watch/trim rationale
- **Concentration & Correlation Notes**: flag any theme clusters, pairwise correlation risks, beta concentration

---

### PAGES 4+ — PER-HOLDING PITCHES (2 PAGES EACH)

One pitch per holding, sorted by Risk-Adj descending (same order as master table).
Each pitch follows this EXACT template:

---
**INTEGRITY COMPOUNDERS · v9 PITCH**

[Sector · Market Cap]

**[Full Company Name] ([TICKER])**

**[Quadrant] — [Quadrant Label]** · Pod: [pod list] · Score: **[score] ([strength label], Rank #[N])** · **[BUCKET]**

| RATING | PRICE | 18-MO BASE | PW ETR | RISK-ADJ |
| [Rating text] | $[price] | $[target] ([pct]%) | [pct]% | [ratio] |
| [Sleeve] | As of [date] | Bull $[x] / Bear $[x] | 18-mo horizon, 25/50/25 | PW ETR / TR σ |

**Thesis**
- **Business:** [2-3 sentence description of what the company does]
- **Bear narrative:** [The legitimate bear case in 2-3 sentences]
- **Bull thesis:** [Why it's in the portfolio — quad placement, score, pod mix, key metrics — 3-4 sentences]

**Model Snapshot**
| Earn Mom (X) | [value]% | Multiple ROC (Y) | [value]% |
| Rev Fwd 2Y CAGR | [x]% (vs 3Y [x]%) | EPS Fwd 2Y CAGR | [x]% (vs 3Y [x]%) |
| Current FCF Yield | [x]% | Forward FCF Yield | [x]% |
| ROIC | [x]% | Op Margin | [x]% |
| Beta | [x] | PEG | [x] |
| Quad Flip Price | $[x] ([pct]%) | Migration | [what happens at flip] |
| FCF Flip Setup | [setup type] | YTD / 1M | [x]% / [x]% |

**18-Month Scenarios · Quadrant-Conditional**
| | Bull (25%) | Base (50%) | Bear (25%) | PW ETR | Risk-Adj |
| Target Price | $[x] | $[x] | $[x] | — | — |
| Total Return | [x]% | [x]% | [x]% | [x]% | [x] |

*Scenarios are model-generated using v9 quadrant-conditional yield multipliers, capped EPS growth,
quality (ROIC, ND/EBITDA) and beta adjustments to the Bear case, plus per-name capital return
over 18 months. Probability weights are 25/50/25 (Bull/Base/Bear).*

**Trade Plan & Monitoring**
- **Sleeve / Sizing:** [sleeve] — current [x]% target weight ([action instruction])
- **Quad flip trigger:** $[x] ([pct]% from current). [What migration means for thesis]
- **Convergence signals:** [N] of 3 positive — FV [+/-], MC [+/-], VC [+/-]. [Interpretation]
- **Stop / review trigger:** [if applicable] Daily close below $[bear target] ([pct]%) with negative forward EPS revisions. Triggers full re-underwrite, not automatic exit.
- **Monitor monthly:** Quad migration (especially to Q3), forward EPS revisions vs. trailing, FCF yield vs current/forward spread.

**Role in Portfolio**
[Pod-based role description. One line per qualifying pod.]

**Decision Log Entry**
| Date | [Month Day, Year] (v9 rebalance) |
| Action | [Maintain/Add/Trim/Review] at [x]% — [rationale] |
| 18-mo Targets | Bull $[x] ([pct]%) · Base $[x] ([pct]%) · Bear $[x] ([pct]%) |
| Why Now | [1-2 sentence thesis for timing] |
| Key Risk | [Primary risk] |
| Conviction Note | Risk-Adj ETR [x] — [tier description]. Alignment Score [x] ([label]). [N] of 3 convergence signals positive. |

*— End of [TICKER] pitch —*
---

---

## SECTION 3 — RATING LABELS

Use these exact rating labels based on quad + signal + Risk-Adj:

| Condition | Rating Label |
|-----------|-------------|
| Q1/Q2 + Accumulate + Risk-Adj ≥ 1.5 | BUY |
| Q1/Q2 + Accumulate + Risk-Adj 1.0-1.5 | BUY |
| Q1/Q2 + Neutral | HOLD — Add on weakness |
| Q4 + Accumulate/Neutral | HOLD — Add on weakness |
| Q3 + any | HOLD (trim/underweight candidate) |
| Any + Distribute | TRIM / REVIEW |
| Discretionary off-screen | HOLD — Discretionary |

---

## SECTION 4 — ALIGNMENT SCORE STRENGTH LABELS

| Score | Label |
|-------|-------|
| 90-100 | Very Strong |
| 80-89 | Very Strong |
| 70-79 | Strong |
| 60-69 | Moderate |
| 50-59 | Moderate |
| 40-49 | Weak |
| 30-39 | Weak |
| 20-29 | Very Weak |
| < 20 | Very Weak |

---

## SECTION 5 — CONVERGENCE SIGNALS

Three signals, each positive or negative:
- **FV (Fundamental Velocity):** Positive if Earnings Mom ROC (X-axis) > 0
- **MC (Market Conviction):** Positive if price momentum (1M return) > 0
- **VC (Valuation Confirmation):** Positive if Multiple ROC (Y-axis) > 0

Signal summary language:
- 3 of 3 positive → "Full alignment — highest-quality setup."
- 2 of 3 positive → "Two of three — solid; check which is dragging."
- 1 of 3 positive → "One or zero — wait for more confirmation before adding."
- 0 of 3 positive → "One or zero — wait for more confirmation before adding."

---

## SECTION 6 — SCENARIO MATH (v9 QUADRANT-CONDITIONAL MULTIPLIERS)

Use these multipliers to generate Bull/Base/Bear price targets when not provided:

**Base Case Target:**
  Base Price = Current Price × (1 + Base Multiple Expansion) × (1 + Fwd EPS CAGR × 1.5yr)

**Quadrant-conditional Base Multiple Expansion:**
| Quadrant | Bull Expansion | Base Expansion | Bear Expansion |
|----------|---------------|----------------|----------------|
| Q1 | +35% | +20% | -5% |
| Q2 | +80% | +40% | +5% |
| Q3 | +15% | +10% | -25% |
| Q4 | +45% | +25% | -15% |

**EPS CAGR cap:** 25% for scenario math (base-effect protection)

**Bear case adjustment:**
- Add beta penalty: Bear Price × (1 - (Beta - 1.0) × 0.05) for Beta > 1.0
- Add quality buffer: Bear Price × (1 + (ROIC - 0.12) × 0.02) for ROIC > 12%
- Add capital return: +1.5% to all scenarios for 18-month capital return accumulation

**Probability-Weighted ETR:**
PW ETR = 0.25 × Bull TR + 0.50 × Base TR + 0.25 × Bear TR

**Risk-Adjusted ETR:**
TR Standard Deviation = standard deviation of [Bull TR, Base TR, Bear TR]
Risk-Adj = PW ETR / TR Standard Deviation

**Quad Flip Price (Y-axis):**
Flip Price = Current Price × (Forward FCF Yield / Current FCF Yield)
This is the price at which Current FCF Yield would equal Forward FCF Yield.
Label: "Loses GARP discount if sells off" for Q2, "Improves to Hidden Value if rallies" for Q1.
Add "WARNING: enters Narrative Rally if sells off" for Q4 names where flip takes them to Q3.

---

## SECTION 7 — DISCRETIONARY HOLDINGS (PLTR OR OTHERS)

Any holding designated as "discretionary" (outside the quant screen):
- Gets its own pitch page with header "DISCRETIONARY HOLDING — OUTSIDE QUANTITATIVE SCREEN"
- No scenario math generated
- Includes: Business description, Bear narrative, Bull thesis
- Compliance section with: Status, Documentation requirement, Position weight, Monitoring triggers, Sizing principle
- Rating: "HOLD — Discretionary" with annual review note
- Decision Log entry must include explicit IC documentation reference

---

## SECTION 8 — FORMATTING RULES

- Brand color: Navy #1F3A5F
- Font: Calibri (or Source Sans 3 as web equivalent)
- Format: US Letter proportions
- All percentages: one decimal (12.3%)
- All multiples: one decimal (1.4×)
- All prices: two decimals with comma separator ($1,062.95)
- Market caps: billions with one decimal ($291.1B) or trillions ($4.8T)
- Quadrant colors: Q1=blue (#2563eb), Q2=green (#16a34a), Q3=red (#dc2626), Q4=orange (#d97706)
- Q3 names labeled: "Trim / Underweight candidate" in sleeve field
- Distribute signal names: "TRIM / REVIEW" rating
- Footer: "Integrity Wealth Partners · Page X of Y"

---

## SECTION 9 — OUTPUT

Save the completed report to:
  outputs/reports/[YYYY-MM]_Integrity_Compounders_Rebalance.html

Also save a plain-text decision log summary to:
  journal/monthly/[YYYY-MM]_rebalance_decisions.md

Open the HTML file in the browser automatically when done.

---

## SECTION 10 — HOW TO TRIGGER THIS

Tell Claude Code any of the following:
- "Generate the monthly rebalance report"
- "Build the June pitch book"
- "Run the rebalance for [month]"
- "Create the pitch book for these holdings: [list tickers]"

Claude Code will:
1. Read this file
2. Pull current data from universe.db for all named holdings
3. Fill in any missing scenario math using Section 6 multipliers
4. Generate the full HTML report in the structure above
5. Save and open it

---

*Integrity Compounders · Integrity Wealth Partners · LPL Financial Affiliate*
*This file governs rebalance report generation. CLAUDE.md governs all other system behavior.*
