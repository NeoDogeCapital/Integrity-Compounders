# Fiscal Financials Pull

Read [the Fiscal MCP contract](mcp-workflow.md). Honor the requested statement, metrics, periods, and currency; do not fetch ratios or all three statements by default.

## Fetch

1. Call `company_financials_standardized({ statementType, companyKey, periodType, currency? })` for each explicitly requested statement. Combine period types in one comma-separated value.
2. Inspect its `metrics` array and select `data[].metricsValues[metricId]` in-sandbox.
3. Call `company_profile` only for template, identity, coverage, or `terminalUrl` context.
4. Call `company_ratios` only when the user asks for derived ratios; do not retrieve it for a raw statement pull.
5. Call `company_financials_as_reported` only for exact filed labels or a source-chain investigation. Call `standardized_metrics_list` only after the response metadata cannot resolve an unusual template-specific line.

## Output

State the company key, statement, period types, currency, and unit. Sort periods chronologically, flag restatements and stub periods, and preserve missing values rather than converting them to zero.

For exports, return exactly the requested columns and all requested rows. Cite values through `asReportedValues[].sources[].auditUrl`, falling back to `originalSourceUrl`. Surface ADR ordinary-share conversion fields when the question is about EPS or weighted-average shares.
