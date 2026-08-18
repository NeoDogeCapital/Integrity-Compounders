# Fiscal Earnings Reaction

Read [the Fiscal MCP contract](mcp-workflow.md). Treat price reaction as the observable market verdict, not as a consensus beat/miss field.

## Fetch

Use one `execute_code` invocation:

1. Fetch in parallel:
   - `company_profile({ companyKey })`
   - quarterly standardized income statement
   - `company_stock_prices({ companyKey })`
2. Use quarterly rows for diluted EPS, revenue, `earningsDate`, `earningsTimeOfDay`, and restatement flags. Do not fetch `company_earnings_summary` unless the statement lacks a required actual.
3. Add one targeted news query only for explaining a specific print.
4. Add peer prices only when the user requests a peer-basket tape proxy; obtain peers from `company_peers`, not a universe scan.
5. When the user asks why management or analysts focused on a topic, add
   [IR events and transcripts](fiscal-ir-events-and-transcripts.md) after calculating the reaction. Fetch only the
   matching call and keep transcript interpretation separate from the observable price move.

## Calculate

- Use `stock.prices[].date`, `closePrice`, and `volume`; sort ascending.
- Headline each print with the close before `earningsDate` to the close after it, a two-session straddle that handles before-open and after-close releases. State that the window can include non-earnings drift.
- For pattern studies, calculate +5 and +21 trading-session drift from the post-reaction close and mark incomplete recent windows.
- Compare EPS and revenue with the prior quarter and year-ago quarter. Classify acceleration only when enough non-stub, non-restated history exists.
- Keep returns raw. A peer basket is context only, not an index, beta adjustment, or excess return.

## Output

Default to the latest print plus a four-quarter table and a two-sentence read. Expand to 8-12 quarters, drift statistics, and acceleration/reaction quadrants only when the user asks how the stock “usually” trades or requests a full pattern study.

Cite EPS and revenue with `auditUrl`; market-price calculations have no filing audit link. Do not infer consensus,
estimate revisions, or price targets from this workflow. For the next earnings date, use `events_calendar` only when
that helper is live and preserve its confirmed, estimated, or projected status.
