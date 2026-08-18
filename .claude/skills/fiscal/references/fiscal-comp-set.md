# Fiscal Comp Set

Read [the Fiscal MCP contract](mcp-workflow.md). Match the depth to the question; a simple two-company comparison does not require full histories, segments, ownership, and daily multiples.

## Select peers

- Keep user-named companies.
- For “versus peers,” call `company_peers({ companyKey })` once and take the highest-relevance peers. Do not scan `companies_list`.
- Default to at most six companies. Explain the cost before expanding toward ten.

## Fetch

Use a core ratio invocation, then deepen in later invocations. Keep every company fan-out to at most six calls:

1. Fetch `company_ratios({ companyKey, periodType: "annual,latest", currency })` for the core comparison, one call per company.
2. Fetch profiles in a later invocation only when profile fields, template checks, or `terminalUrl` are needed.
3. Reduce ratio responses first, then fetch one income statement per company with `periodType: "annual,quarterly,ltm"` in another invocation only when absolute financials, latest-quarter momentum, or metric sourcing is needed.
4. Add segments only for business-mix comparisons. Add a daily multiple only for “cheap versus own history.” Add insider activity only when explicitly requested.

For more than six companies, continue each phase in deterministic groups of at most six rather than putting several
waves into one 30-second execution.

## Compare

Choose a coherent panel from market cap, P/E, EV/EBITDA, price/sales, revenue and EPS growth, gross/operating/net margins, ROE/ROIC, net-debt/EBITDA, and interest coverage. Use values actually present in ratio metadata; do not invent missing IDs.

Normalize monetary comparisons to one currency, flag different reporting templates when profile data were fetched, compare matching fiscal periods, and separate business quality from valuation. Output a compact table, one winner by dimension, and the main comparability caveats. Cite filing-backed absolute figures with `auditUrl` and link company names with `terminalUrl` when fetched.
