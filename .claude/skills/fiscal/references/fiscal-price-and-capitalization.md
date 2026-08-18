# Fiscal Price and Capitalization

Read [the Fiscal MCP contract](mcp-workflow.md). Remember that stock prices are nested under `prices` and use camelCase fields.

## Fetch

- Price or returns: `company_stock_prices({ companyKey })` only; slice `result.prices` in-sandbox.
- Splits: add `company_stock_splits` only for split questions.
- Share count/dilution: add `company_shares_outstanding` only for share questions.
- Market cap or EV context: add one `company_ratios({ companyKey, periodType: "latest,annual" })`; do not call it twice.
- Historical valuation/capitalization series: add only the requested curated `company_daily_ratios` IDs.
- Fetch `company_profile` only when identity, pre-IPO status, or `terminalUrl` is needed.

## Calculate and output

Sort `prices` ascending. Calculate returns using the closest trading session on or before each requested anchor date; disclose the price-only nature of returns. The payload provides split-adjusted `openPrice`, `closePrice`, and `volume`, but no daily high/low through this MCP helper.

Label `tradingCurrency` from the stock response separately from reporting currency. Distinguish ADS and ordinary shares when conversion fields exist. Do not calculate total shareholder return or dividend income without a dividend cash-flow series. Keep same-day volume caveated as potentially incomplete.
