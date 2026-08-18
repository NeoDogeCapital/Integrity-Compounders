# Fiscal Industry Report

Read [the Fiscal MCP contract](mcp-workflow.md). Keep the default universe small enough to finish reliably; deepen survivors instead of running every endpoint on every company.

## Define the universe

- If the user gives a seed company, fetch its profile and `company_peers` first.
- If the user gives only an industry label, page through `companies_list` only until enough matching active, non-pre-IPO candidates are found. Filter on returned sector/industry/subIndustry fields before company calls.
- Default to 8-12 representative companies, balanced across leaders and challengers. Ask before exceeding 15.

## Fetch in stages

Use two `execute_code` phases by default:

1. Discovery/ranking: fetch
   `company_ratios({ companyKey: candidate.companyKey, periodType: "latest,annual" })` for candidates in batches of
   at most six, reduce to ranking fields, and select the final peer set.
2. Deepening: fetch one combined annual/quarterly income statement for the final peers in batches of at most six. Add segments/KPIs only for the few companies where business-mix comparison matters.
3. Add `top_news` for each requested window of at most seven days; set `minMarketCap: 0` when post-filtering to the peer set so small challengers are not excluded by the default $1B floor. Inspect `pagination.hasNextPage` and continue pages until complete or a disclosed page cap is reached. Budget at most six page calls per invocation, not six date windows. Do not call news per peer by default.
4. Run ownership as a separate optional pass only if the user explicitly asks for sponsorship/positioning.
5. For a requested management-commentary or professional-investor lens, select only the few companies that survived
   ranking, then use [IR events and transcripts](fiscal-ir-events-and-transcripts.md) or
   [fund-letter research](fiscal-fund-letter-research.md). Do not fetch every transcript or every thesis feed across
   the discovery universe.

## Analyze and output

Cover industry structure, size/growth proxies, margin and return dispersion, leverage, valuation, business-mix
differences, leaders/laggards, and evidenced catalysts or risks. Use descriptive labels such as revenue share of the
selected public peer set; never call it total market share.

State the universe definition and omissions. Normalize currencies for absolute comparisons, warn on
template/fiscal-calendar differences, and cite filing-backed figures with `auditUrl`.
