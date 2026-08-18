# Fiscal News and Events

Read [the Fiscal MCP contract](mcp-workflow.md). Use server filters once; do not retry importance levels sequentially.

## Fetch

- One company, latest high-signal news: `top_news({ companyKey, minImportance: 1, maxImportance: 2, pageSize })`.
- Cross-company or multiple event types: use `top_news` with comma-separated `eventType`, an importance range, exact dates, and pagination. Split ranges into exact, non-overlapping windows of at most seven days. The cross-company default has a $1B market-cap floor; pass `minMarketCap: 0` only when the request includes smaller companies.
- A one-company range longer than seven days: use `company_news` in exact, non-overlapping windows of at most 31 days. Its `importance` accepts one exact score, so omit it and rank locally when a range is needed. Run at most six windows per invocation; continue longer histories in another invocation.
- Fetch stock prices only when the user asks for market reaction. Do not add a price call to a normal digest.
- For upcoming earnings dates, IR resource packages, or what management said on a call, use
  [IR events and transcripts](fiscal-ir-events-and-transcripts.md) rather than treating a news headline as the
  underlying event or quotation.

## Rank and output

Deduplicate by `sourceUrl`, falling back to company key + `date` + title, then sort by importance ascending and `collectedAt` descending. Lead with what changed and why it matters. Include `date`, company, `eventType`, `importance`, concise impact, and `sourceUrl`.

State the searched date range and filters. Treat 403 or empty plan-gated news as unavailable, not proof that no event occurred. Do not turn dividend announcements into dividend-history data or analyst headlines into Fiscal consensus estimates.
