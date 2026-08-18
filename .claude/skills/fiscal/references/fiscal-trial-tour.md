# Fiscal Trial Tour

Read [the Fiscal MCP contract](mcp-workflow.md) and [trial ticker list](trial-tickers.md) before validating a user-provided company.

## Budget

- Use only companies in the bundled trial list. Treat the server’s live 403 response or `api_docs` free-plan notice as authoritative if the list has drifted.
- Target five MCP helper calls, leaving a sixth attempt for one retry. Profiles and filing-backed financials may make additional service requests, so do not describe this as the total subrequest count or spend the full daily allowance merely to demonstrate breadth.
- Never fetch filing images/PDFs or full price histories in the default tour.

## Default flow

Use one `execute_code` call:

1. Choose two trial companies with different regions or business models.
2. Fetch two profiles and two
   `company_ratios({ companyKey, periodType: "latest,annual" })` calls in parallel, using the matching key for each
   company.
3. Fetch one standardized income statement for one company to demonstrate filing-backed data.
4. Add news only when requested and no retry was needed; it is not part of the five-call default.

## Output

Render a compact side-by-side comparison and one source-linked financial example. Include up to three material
headlines only when the optional news call ran. Explain what each data surface demonstrates and suggest one next
workflow. If a user names a non-trial company, offer a trial substitute rather than repeatedly calling a forbidden
ticker.
