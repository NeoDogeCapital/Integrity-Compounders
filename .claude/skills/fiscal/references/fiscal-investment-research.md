# Fiscal Investment Research

Read [the Fiscal MCP contract](mcp-workflow.md). Treat this as an orchestrated research workflow with a shared data manifest; never repeat a call because another section needs the same payload.

## Scope first

Honor section-specific requests. Run the full workflow only when the user asks for a complete note. Use Fiscal MCP as
the sole evidence source. If it does not carry required qualitative context, state that limitation.

## Build one logical data manifest

Use separate bounded `execute_code` phases and never repeat a payload already fetched:

1. Subject core: fetch `company_profile`, `company_peers`, the three requested standardized statements, and `company_ratios` in staged batches of at most six. Fetch segments/KPIs only after profile coverage is confirmed. Return a reduced subject manifest rather than raw histories.
2. Optional subject lenses: add adjusted metrics only for earnings-quality work, shares/prices/daily multiples only for valuation or market-reaction work, filings only for a specific disclosure, and ownership only for an ownership section. Keep heavy or binary filing work isolated.
3. Catalysts: use one targeted `top_news` or `company_news` plan for the requested window, respecting seven-day and 31-day limits. Do not fetch news independently for each section.
4. Peers: fetch peer ratios in batches of at most six; deepen only the 3-5 final peers with statements or segments in a later invocation.
5. Primary commentary: add IR events/transcripts or company fund letters only when the thesis needs management or
   professional-investor views. Select the relevant events or letters first; do not fetch every transcript or PDF.

## Research structure

Use only sections justified by the request:

1. Investment view and variant perception
2. Business model, segments, and KPIs
3. Historical growth, margins, returns, cash conversion, and balance sheet
4. Competitive position and peer evidence
5. Earnings quality and capital allocation
6. Valuation with explicit assumptions
7. Ownership and management alignment
8. Catalysts, risks, disconfirming evidence, and monitoring points

## Analytical rules

- Separate facts, derived calculations, assumptions, and judgment.
- Do not fabricate consensus, estimates, guidance, market share, proxy data, debt maturities, or price targets when
  unavailable. Use transcripts and fund letters only when their live helpers and company coverage confirm them.
- Use the correct reporting template and fiscal calendar. Explain ADR/per-share conversions when relevant.
- Challenge the thesis with at least two evidence-based failure modes.
- Prefer a concise note that answers the thesis over a fixed word count.

## Output

Lead with the investment conclusion, then the strongest evidence and risks. Cite filing-backed numbers with `auditUrl`, company links with `terminalUrl`, and material news with its source link. End with the assumptions and missing-data limitations that would change the conclusion.
