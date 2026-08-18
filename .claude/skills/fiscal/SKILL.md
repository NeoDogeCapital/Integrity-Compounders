---
name: fiscal
description: Uses the production Fiscal.ai MCP for source-linked public-company data and research, including company discovery, filings, financial statements, segments and KPIs, prices, capitalization, ratios, news, earnings events and transcripts, fund letters, ownership, peer comparisons, screening, watchlists, financial models, valuation, earnings analysis, accounting quality, credit analysis, industry reports, and investment research. Use whenever a user asks for Fiscal.ai data or public-company financial, market, filing, monitoring, modeling, or equity-research work. Accept a natural-language problem, select and compose the smallest relevant bundled workflows, and adapt as the question develops. Uses only the regular Fiscal.ai MCP available to the signed-in user.
---

# Fiscal

Use Fiscal.ai as a flexible public-company research system. Pick up the user's question as stated, discover missing
identifiers or scope through the live connector, and choose the smallest workflow that can answer it.

## Scope

Use only the production Fiscal.ai MCP available in the current session.

- Access data only through `api_docs` and `execute_code`.
- If a requested dataset or action is not exposed by the live connector, state that it is unavailable.
- Do not claim a dataset or account action is available until its live helper, coverage, and entitlement have been
  confirmed. Do not turn news headlines into consensus data or infer market share, debt maturities, covenant headroom,
  or price targets from unrelated payloads.
- Never fill missing Fiscal data with remembered values.

## Start every request

1. Read [the Fiscal MCP execution contract](references/mcp-workflow.md).
2. Interpret the desired outcome, not just keywords. Resolve an unknown company once; reuse a canonical
   `EXCHANGE_TICKER` key already established in the conversation.
3. Select the narrowest matching workflow below. Read only that reference, plus another reference when the request
   genuinely combines outcomes.
4. Reuse fetched payloads across composed workflows. Do not repeat a call because another section needs the same data.
5. Ask a question only when a material choice cannot be discovered or safely inferred, such as valuation assumptions,
   an undefined comparison date, or approval to expand a large universe.

Do not force users through an intake sequence. A request may begin as a snapshot, deepen into valuation, and end as a
monitoring plan in one conversation.

## Choose and compose workflows

### Retrieve and understand company data

| User outcome | Read |
| --- | --- |
| Compact overview or tear sheet | [Company snapshot](references/fiscal-company-snapshot.md) |
| Specific statement lines or history | [Financials pull](references/fiscal-financials-pull.md) |
| Full historical three-statement model | [Financial model](references/fiscal-financial-model.md) |
| Business segments, geography, or operating KPIs | [Segments and KPIs](references/fiscal-segments-and-kpis.md) |
| Prices, returns, splits, shares, market cap, or EV | [Price and capitalization](references/fiscal-price-and-capitalization.md) |
| Historical valuation multiple or percentile | [Ratio trend](references/fiscal-ratio-trend.md) |
| GAAP/IFRS versus company-adjusted results | [Adjusted earnings quality](references/fiscal-adjusted-earnings-quality.md) |
| 10-K, 10-Q, 8-K, report, filing, page, or source | [Filing finder](references/fiscal-filing-finder.md) |
| Company or market news and event timeline | [News and events](references/fiscal-news-and-events.md) |
| Earnings dates, IR materials, or call transcripts | [IR events and transcripts](references/fiscal-ir-events-and-transcripts.md) |
| Professional-investor letters, firms, or company theses | [Fund-letter research](references/fiscal-fund-letter-research.md) |
| Insider transactions, institutions, or 13F | [Ownership activity](references/fiscal-ownership-activity.md) |
| Saved Fiscal watchlists, portfolios, or other account data | [Account tools](references/fiscal-account-tools.md) |

### Compare, analyze, and value

| User outcome | Read |
| --- | --- |
| Side-by-side comparison of 2–6 companies | [Comp set](references/fiscal-comp-set.md) |
| DCF, reverse DCF, multiples, fair value, or IRR | [Valuation](references/fiscal-valuation.md) |
| Sources and uses, buybacks, dividends, M&A, or capex | [Capital allocation](references/fiscal-capital-allocation.md) |
| Leverage, liquidity, coverage, or solvency | [Credit and solvency](references/fiscal-credit-and-solvency.md) |
| Piotroski, Altman, Beneish, Sloan, or named score | [Quality scores](references/fiscal-quality-scores.md) |
| Historical earnings-day moves or post-earnings drift | [Earnings reaction](references/fiscal-earnings-reaction.md) |
| Segment-level or breakup valuation | [Sum of the parts](references/fiscal-sum-of-the-parts.md) |

### Screen, monitor, and research broadly

| User outcome | Read |
| --- | --- |
| Find and rank companies by criteria | [Screener](references/fiscal-screener.md) |
| Sector or industry landscape | [Industry report](references/fiscal-industry-report.md) |
| What changed across a supplied list | [Watchlist monitor](references/fiscal-watchlist-monitor.md) |
| Full source-backed investment memo | [Investment research](references/fiscal-investment-research.md) |
| Free-plan demonstration | [Trial tour](references/fiscal-trial-tour.md) and [trial tickers](references/trial-tickers.md) |

## Composition rules

- Prefer a retrieval workflow for a narrow fact request. Do not invoke a model, deep-dive note, or broad screen when one
  statement, filing, ratio, or news call answers the question.
- Use an orchestrating workflow—snapshot, industry report, watchlist, investment research, or trial tour—only when the
  requested deliverable needs it.
- For a compound request, build one logical data manifest and apply several analytical lenses to it. Example: a
  snapshot plus valuation should reuse the profile, ratios, and financials.
- For breadth, reduce first and deepen later. Respect each workflow's company, window, pagination, concurrency, and
  call-budget limits.
- Let live profile coverage and entitlements determine optional routes. A visible tool does not prove the account has
  the dataset.
- Treat account-scoped write or delete helpers as separate consequential actions. Never invoke them as part of a
  research workflow unless the user explicitly asks for that exact change.
- Use Fiscal MCP for all evidence. If it does not carry required qualitative context, state the limitation instead of
  silently substituting another source.

## Financial-model templates

For a full financial model, fetch the profile first and load exactly one template matching
`company_profile.reportingTemplate`:

- [Standard](references/template-standard.md)
- [Financials](references/template-financials.md)
- [Insurance](references/template-insurance.md)
- [Real estate](references/template-real-estate.md)
- [Utilities](references/template-utilities.md)
- [Capital markets](references/template-capital-markets.md)

Do not load these templates for a narrow financials pull.

## Output contract

- Lead with the answer, conclusion, or ranked result the user requested.
- State the company key, relevant periods or dates, currency, units, and comparison basis.
- Cite filing-backed figures with `auditUrl`, falling back only as the MCP contract permits. Use `terminalUrl` for the
  company-level Fiscal link and public news or filing source URLs where available.
- Separate reported facts, derived calculations, assumptions, and judgment.
- Preserve missing values; do not convert them to zero or infer absence from an empty or entitlement-gated response.
- State searched windows, universe definitions, exclusions, partial failures, and plan limits that affect the result.
- Keep a simple question compact. Use tables, files, or multi-stage output only when the requested deliverable benefits
  from them.
