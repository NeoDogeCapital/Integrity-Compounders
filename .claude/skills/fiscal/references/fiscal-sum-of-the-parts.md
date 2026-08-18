# Fiscal Sum of the Parts

Read [the Fiscal MCP contract](mcp-workflow.md). A SOTP is assumption-driven: use Fiscal for historical segment evidence and capitalization, and label valuation inputs separately.

## Fetch

Build the subject in one invocation and comparables in later invocations:

1. Fetch `company_profile` and require segment/KPI coverage.
2. After the gate, fetch in one parallel batch:
   - `company_segments_and_kpis({ companyKey, periodType: "annual,quarterly" })`
   - annual standardized income statement
   - `company_ratios({ companyKey, periodType: "latest,annual" })`
   - the balance sheet only when net debt, investments, pensions, minority interests, or other equity bridges are not
     available in ratios
3. In a later invocation, call `company_peers`, select at most five user-approved comparable companies, and fetch
   their ratios in one batch. Do not assume company-level peers are valid segment comps.
4. Fetch any comparability statements or daily-multiple history in another invocation only when required.

## Value

- Define each segment, historical revenue/profit/KPI basis, chosen method, multiple or DCF assumptions, and resulting enterprise value.
- Use segment values only where directly reported; do not allocate corporate totals without an explicit rule.
- Reconcile segment enterprise values to group enterprise value, then bridge net debt and other claims to equity value and diluted per-share value.
- Show a sensitivity range for the largest assumptions and state the current market-implied conglomerate discount/premium.
- Do not fabricate segment EBITDA, capex, D&A, consensus, or market share when absent.

## Output

Return a segment valuation table, equity bridge, per-share range, sensitivity table, and the assumptions that drive the conclusion. Cite historical inputs with `auditUrl`; identify assumptions as assumptions, never Fiscal facts.
