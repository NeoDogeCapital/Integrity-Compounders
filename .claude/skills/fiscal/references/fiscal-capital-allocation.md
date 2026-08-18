# Fiscal Capital Allocation

Read [the Fiscal MCP contract](mcp-workflow.md). Build the analysis in stages so optional M&A, valuation-history, and insider lenses do not burden a basic sources-and-uses request.

## Fetch

Build the core first, then use separate enrichment invocations:

1. In the core invocation, call `company_profile({ companyKey })`. Exit for pre-IPO companies. Adapt the framework for financials, insurers, real estate, utilities, and capital-markets templates instead of forcing a generic free-cash-flow frame.
2. After the profile, fetch the requested 5-10 annual years in one parallel batch:
   - three `company_financials_standardized` statements
   - `company_ratios({ companyKey, periodType: "annual,latest" })`
3. In a later invocation, add `company_shares_outstanding` only for buyback execution, `company_stock_prices` only for repurchase-price context, and one curated `company_daily_ratios` series only when the user asks whether buybacks occurred at cheap multiples.
4. Identify heavy acquisition years before calling news. In a separate news invocation, query only those periods with `company_news({ companyKey, eventType: "ma", startDate, endDate })`, using non-overlapping 31-day windows and at most six windows per invocation. Run insider transactions as another optional pass only when requested.
5. If the user specifically asks how professional investors assess management or capital allocation, add
   [fund-letter research](fiscal-fund-letter-research.md) after the quantitative work. Keep each investor's dated view
   separate from the company's reported actions.

## Analyze

- Build annual sources and uses from operating cash flow, capex, acquisitions, dividends, repurchases, debt issuance/repayment, and change in cash. Preserve statement signs and label unavailable lines as not separately disclosed.
- Use returned buyback, debt-paydown, dividend, and shareholder-yield ratios when available.
- Compare gross repurchase cash with net share-count change; explain stock-compensation offset.
- Treat repurchase cash divided by shares retired as approximate, not a precise average purchase price.
- Assess dividend coverage by free cash flow, capex intensity, goodwill/impairment evidence, leverage direction, and ROIC/ROCE trajectory.
- Do not infer a debt-maturity schedule, covenant headroom, or remaining authorization from these endpoints.

## Output

Return one annual table, short scorecards for the requested levers, and a synthesis of management priorities and value creation. Cite statement figures with `auditUrl`; use news only to name evidenced deals.
