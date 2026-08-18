# Fiscal Filing Finder

Read [the Fiscal MCP contract](mcp-workflow.md). Start with the filing catalog and do not fetch binary documents merely to provide a link.

## Fetch

1. Call `company_filings({ companyKey })` once.
2. Filter the returned rows inside `execute_code` by `documentType`, date, fiscal year/quarter, and `secFormType` where
   available. There is no separate amendment-status field; treat a `documentType` ending in `"(Amended)"` as amended.
3. Map common US requests: 10-K to `Annual Report`, 10-Q to `Interim Report`, 8-K to `Current Report`, and earnings release to `Earnings Press Release`. For non-US companies, prefer `documentType` over SEC form labels.
4. Call `filing_page_image({ filingId, pageNumber, companyKey })` only when the model must read a known page. Do not use `filing_pdf` to scan a document or obtain a link. If the user explicitly requests the binary, keep that call isolated; for a large filing, explain that the MCP output path is unsuitable and return the public `sourceUrl` instead.

For an earnings package rather than a statutory filing, use
[IR events and transcripts](fiscal-ir-events-and-transcripts.md): `company_ir_events` groups the interim or annual
report, slide deck, press release, transcript, and audio availability by event. Do not expect all of those resources
to appear in `company_filings`.

## Output

Return the smallest matching set with filing/report date, fiscal period, document type, SEC form when present, and
amended status derived from the document type. Prefer a public `sourceUrl` for the document link. Never log base64
merely to surface a document, and never expose API `pdfUrl`, `document`, `image`, or base64 as clickable links.

Treat an amended filing as potentially authoritative over the original. For data-point evidence, prefer the `auditUrl` already carried by financial-source arrays instead of calling a filing binary tool.
