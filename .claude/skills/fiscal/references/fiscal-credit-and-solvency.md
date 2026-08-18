# Fiscal Credit and Solvency

Read [the Fiscal MCP contract](mcp-workflow.md). Use template-aware ratios and statements; do not claim maturity or covenant information the MCP does not carry.

## Fetch

Use one staged `execute_code` invocation:

1. Fetch `company_profile({ companyKey })` for template, currency, pre-IPO status, and link.
2. Fetch in parallel:
   - `company_ratios({ companyKey, periodType: "annual,latest" })`
   - annual standardized balance sheet
   - annual standardized income statement
3. Add quarterly ratios and balance sheet only when recent deterioration, cash burn, or a turning point is central.
4. Add financing news only when requested, using targeted
   `company_news({ companyKey, eventType: "financing", startDate, endDate })` windows of at most 31 days after
   identifying the relevant period.

## Analyze

- Leverage: total debt, net debt, net-debt/EBITDA, debt/equity, and debt/capitalization.
- Composition: short-term debt/current portion, long-term debt, lease liabilities when separately reported, cash, and equity.
- Coverage: EBIT and EBITDA interest coverage; use magnitudes if the API signs interest expense as negative and state that convention.
- Liquidity: current, quick, and cash ratios; for negative FCF, estimate cash runway from recent burn and label the missing revolver/committed-liquidity caveat.
- Direction: distinguish debt paydown from EBITDA recovery and one-off balance-sheet changes.

## Output

Provide a compact multi-year table and a plain-language credit verdict. Cite statement components with `auditUrl`. State explicitly that Fiscal does not provide agency ratings, debt maturities, covenant headroom, or committed facilities; direct users to the latest filing for those details.
