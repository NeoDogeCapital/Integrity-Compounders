# Fiscal Adjusted Earnings Quality

Read [the Fiscal MCP contract](mcp-workflow.md), then measure the adjustment gap without substituting historical actuals for consensus.

## Fetch

Use one `execute_code` invocation:

1. Call `company_profile({ companyKey })` and require `availableDatasets` to include `adjusted_numbers`. Stop clearly when coverage is absent.
2. After the gate, fetch in parallel:
   - `company_adjusted_metrics({ companyKey, periodType: "annual,quarterly,ltm" })`
   - `company_financials_standardized({ statementType: "income-statement", companyKey, periodType: "annual,quarterly,ltm" })`
   - `company_ratios({ companyKey, periodType: "annual,latest" })`
3. Fetch `company_financials_as_reported` only when the user asks what drove the gap. Fetch `company_earnings_summary` only for actual earnings dates or actual EPS/revenue; it is not consensus.
4. When the user asks how management explained recurring adjustments, use
   [IR events and transcripts](fiscal-ir-events-and-transcripts.md) as a later qualitative pass. Select the relevant
   calls first and do not substitute commentary for the reported adjustment bridge.

## Analyze

- Join adjusted and reported rows by fiscal period identity and period type, not date alone.
- Report only metrics present in both payloads. Show reported value, adjusted value, absolute gap, percentage gap, and direction over the available adjusted history.
- Center the conclusion on adjusted-minus-reported net income/EPS, persistence of one-directional gaps, recurring restructuring or impairment charges, acquired-intangible amortization, and stock-based compensation intensity.
- Cross-check with operating-cash-flow/net-income and free-cash-flow/net-income ratios returned by `company_ratios`. Do not re-derive a ratio already present.
- Count and disclose the actual adjusted-history depth; it is commonly shorter than standardized history.

## Output

Give a compact bridge, the largest recurring adjustment drivers, cash-conversion evidence, and a plain-language
verdict. Cite adjusted and reported figures with `auditUrl`. Do not treat `company_earnings_summary`, news headlines,
or this historical adjustment series as forward analyst consensus, estimate revisions, or price targets.
