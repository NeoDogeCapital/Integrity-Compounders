# Fiscal Ratio Trend

Read [the Fiscal MCP contract](mcp-workflow.md). Avoid catalog and profile calls when the user asks for a known ratio on a known company key.

## Fetch

1. For curated common IDs such as `ratio_price_to_earnings`, `ratio_ev_to_ebitda`, `ratio_price_to_sales`, and `ratio_price_to_book`, call `company_daily_ratios({ ratioId, companyKey, currency? })` directly.
2. Call `ratios_list()` only for an unfamiliar user-named ratio or when a curated ID fails; verify `hasDailyData` and report `formulaHuman`.
3. Fetch multiple requested series in parallel within one `execute_code` invocation.
4. Add `company_ratios({ companyKey, periodType: "latest,annual" })` only for a current fundamental snapshot,
   `company_profile` only for a link/template, and quarterly financials only for requested earnings annotations.

## Analyze and output

Use daily rows `{ date, ratio }`. Sort ascending, remove null and non-finite observations, and calculate the requested range, latest value, median, mean, min/max, and latest percentile. For skewed multiple series, emphasize median and percentiles over the mean.

Do not infer fair value or a target price unless the user explicitly requests a valuation model and supplies or accepts assumptions. If a ratio lacks daily data, offer periodic `company_ratios` instead.
