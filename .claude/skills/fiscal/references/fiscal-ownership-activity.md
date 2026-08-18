# Fiscal Ownership Activity

Read [the Fiscal MCP contract](mcp-workflow.md). Route to the smallest ownership endpoint set that answers the question.

## Fetch by intent

- Insider activity: `company_insider_transactions({ companyKey, includeInactive?, pageNumber, pageSize })`. Add `company_insider_holders` only when current roles/holdings are needed.
- Company institutional holders: `company_institutional_holders({ companyKey, year?, quarter?, pageNumber, pageSize })`; omit year and quarter for latest. Supply both for history.
- Named institution portfolio: call `holder_institutional_holdings` with exactly one known `holderId` or `cik`.
  `institutional_holders_list` can filter by CIK but not by name. If only a name is known, obtain its CIK first or
  scan a small, disclosed page cap and report an unresolved partial result rather than paging the whole directory.
- Add `company_stock_prices` only to contextualize transaction prices. Fetch ownership filing PDFs only when the user explicitly requests source-document reading.

Use one `execute_code` invocation for one resolved intent. Fetch requested companies or quarters in parallel, cap
default page size to what the output needs, and inspect pagination before fetching another page. Resolve an unknown
institution separately before fetching its portfolio.

## Classify carefully

- Separate open-market purchases/sales from grants, awards, option exercises, tax withholding, and gifts using returned `transactionType`.
- Report transaction date, insider/holder, role, shares, price/value, post-transaction holdings, and filing date only when those fields are present.
- Treat 13F data as reported positions, not real-time holdings. Use reported quarter labels and distinguish shares/value change from price-driven value movement.
- Never interpret an empty or 403 response as “no insiders” or “no institutions”; state coverage or entitlement uncertainty.

## Output

Default to a compact activity table and a short accumulation/distribution read. For trajectories, show only the requested quarters and concentration changes. Link public filing/source URLs when returned; never expose API PDF URLs or base64 payloads.
