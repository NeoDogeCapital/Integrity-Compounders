# Fiscal Segments and KPIs

Read [the Fiscal MCP contract](mcp-workflow.md). Do not reconstruct segment tables from consolidated statements when dedicated coverage is absent.

## Fetch

Use one staged `execute_code` invocation:

1. Call `company_profile({ companyKey })` and require `availableDatasets` to include `segments_and_kpis`.
2. After the gate, call `company_segments_and_kpis({ companyKey, periodType: "annual,quarterly", currency? })` once. Do not make separate annual and quarterly calls.

## Analyze and output

Join metric metadata, segment groups, rollups, and period values by stable numeric `metricId`, never by display name. Prioritize important metrics, economic drivers, and continuous history. Respect `metricFormat`, units, discontinued flags, and rollups; do not double-count a rollup with its components.

Explain the drivers before the table. Show the requested annual/quarterly trend, mix shift, growth, and margins only where directly supported. Link the company with `terminalUrl` and cite filing-backed values with `auditUrl` when present.
