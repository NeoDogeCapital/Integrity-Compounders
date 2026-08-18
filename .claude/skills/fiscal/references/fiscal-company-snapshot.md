# Fiscal Company Snapshot

Read [the Fiscal MCP contract](mcp-workflow.md). Keep the default answer to one screen and make enrichment request-shaped.

## Fetch

Use one `execute_code` invocation:

1. Fetch `company_profile({ companyKey })` and `company_ratios({ companyKey, periodType: "latest,annual" })` in parallel.
2. Fetch one annual income statement only for latest revenue, EBIT, EPS, and margin context.
3. Fetch `company_stock_prices` only when the user asks for performance or when a price panel is central. Slice the nested `prices` array in-sandbox.
4. Fetch `top_news({ companyKey, minImportance: 1, maxImportance: 2, pageSize: 3 })` only for recent developments.
5. Do not fetch daily multiples, insiders, or institutional holders in the default snapshot. Add them only when asked.
6. Add [IR events and transcripts](fiscal-ir-events-and-transcripts.md) or
   [fund-letter research](fiscal-fund-letter-research.md) only when the requested snapshot includes management
   commentary or professional-investor views. Do not make either part of the default snapshot.

## Output

Show company and business description; sector/industry; reporting and trading currency; latest revenue, operating profit, EPS, and growth; market cap; a small valuation/profitability/leverage panel; and optional price returns or top three headlines.

Use ratio IDs present in the payload, commonly `calculated_market_cap`, `ratio_price_to_earnings`, `ratio_ev_to_ebitda`, `ratio_return_on_equity`, and `ratio_net_debt_to_ebitda`. Omit price and market-cap sections for pre-IPO names. Link the first company mention with `terminalUrl` and cite filing-backed figures with `auditUrl`.
