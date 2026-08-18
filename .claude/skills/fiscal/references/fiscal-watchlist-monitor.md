# Fiscal Watchlist Monitor

Read [the Fiscal MCP contract](mcp-workflow.md). Use a breadth-first scan followed by flagged-name deepening so a 25-name list does not become hundreds of calls.

## Scope

- Require a watchlist and a comparison date/window. Reuse company keys already provided; resolve unknown names once.
- Default to at most 15 names for a full scan. For 16-25 names, run the lightweight pass and ask before deepening many names.
- Compare against user-provided prior values or data available through the live Fiscal MCP. Do not assume persistent
  state outside the connector.

## Lightweight pass

Keep each pass to one monitoring lens:

1. For news, split the exact window into non-overlapping
   `top_news({ startDate, endDate, minImportance, maxImportance, minMarketCap: 0, pageNumber, pageSize })` chunks of at
   most seven days and filter `data` to the watchlist. Inspect `pagination.hasNextPage` for every chunk. Budget at most
   six page calls per invocation, including follow-up pages, and continue remaining windows/pages in another
   invocation. Set `minMarketCap: 0` so the cross-company feed does not silently apply its default $1B floor.
2. For a company-specific lens, fetch only one endpoint per pass in batches of at most six:
   - `company_filings` for new filings
   - `company_ratios({ companyKey, periodType: "latest,annual" })` for current gauges
   - `company_stock_prices` for requested price thresholds, slicing nested `prices`
   - `events_calendar` for future-event alerts when that helper is live; bundle the known company keys into one call
     and preserve each event's returned status
   - `company_ir_events` for earnings-material availability; call an item newly available only when the user supplies
     prior resource IDs or event periods to compare, and fetch a transcript only for a flagged event
   - `company_fund_letters` for professional-investor theses; call a thesis newly published or changed only when the
     user supplies prior letter IDs, reporting periods, or another reliable comparison basis
3. If the user requests multiple lenses, run separate `execute_code` passes rather than multiplying every lens across every company in one run. Skip profiles when keys and identity are already known. Skip earnings summaries, daily ratios, and insiders unless those alerts were requested.

## Deepen flagged names

After the lightweight pass, fetch detailed statements, daily ratios, company-specific news windows, call transcripts,
fund-letter details, or insider transactions only for companies that crossed an explicit threshold or had a material
event. Deepen at most six names per invocation and use `Promise.allSettled` so one entitlement failure does not erase
the dashboard. Follow [IR events and transcripts](fiscal-ir-events-and-transcripts.md) and
[fund-letter research](fiscal-fund-letter-research.md) for those two lenses.

A current-only pull can report the latest available event resources or theses, but not when the connector first
received them. Label it as a latest-state snapshot rather than a “new since last run” alert when no baseline exists.

## Output

Lead with actionable changes ranked by severity, then show unchanged names compactly. For every alert, include the trigger, before/after value or event date, why it matters, and source. State the exact window, lenses run, failed/entitlement-gated names, and whether the comparison used user-provided prior state or only data available in the current run.
