# Fiscal Financial Model

Read [the Fiscal MCP contract](mcp-workflow.md). Read exactly one template skeleton from this directory after `company_profile.reportingTemplate` is known:

- `template-standard.md`
- `template-financials.md`
- `template-insurance.md`
- `template-real-estate.md`
- `template-utilities.md`
- `template-capital-markets.md`

## Fetch

Use a core invocation plus conditional enrichment when needed:

1. Fetch `company_profile({ companyKey })` and select the template.
2. Fetch the core model in one batch of at most six:
   - standardized income statement, balance sheet, and cash-flow statement with `periodType: "annual,quarterly"`
   - `company_ratios({ companyKey, periodType: "annual,quarterly,latest" })`
   - `company_shares_outstanding({ companyKey })` when per-share modeling is needed
   - `company_stock_splits({ companyKey })` only when split history matters
3. Reduce the core payloads to the requested model periods before output. Fetch `company_segments_and_kpis({ companyKey, periodType: "annual,quarterly" })` in a later invocation only when coverage exists and driver modeling benefits from it.
4. Fetch adjusted metrics in that enrichment phase only when the user requests an adjusted model and coverage exists. Use as-reported statements or filing pages only to resolve a specific disclosure question.

## Build

- Preserve the template skeleton’s row order and select actual returned metric IDs from `metrics`; do not assume Standard-template IDs work elsewhere.
- Join statement rows by fiscal period identity. Mark restatements, stub periods, and currencies/units.
- Keep historical actuals separate from assumptions and forecasts. Never invent consensus; projections require explicit user assumptions or clearly labeled scenarios.
- Reconcile cash: opening cash + operating + investing + financing + FX/other = closing cash where data supports it.
- Reconcile EPS/share count, balance-sheet equality, and cash-flow signs. Do not force a plug without disclosure.
- Use stable segment/KPI `metricId` joins and avoid double-counting rollups.

## Output

Return a model-ready annual and quarterly table, key drivers, reconciliation checks, and an assumptions block. Cite filing-backed actuals with `auditUrl`. Keep the default historical depth to what the user requested; do not automatically pull every available period.
