# Fiscal MCP execution contract

Use this contract for every Fiscal workflow. It reflects the production Fiscal.ai MCP execution surface.

## Write valid sandbox code

- The connector exposes two public tools: `api_docs` for the session-specific helper catalog and `execute_code` for
  running code. Data helpers are injected as `codemode.*` functions inside `execute_code`; they are not separate MCP
  tools.
- Generate plain JavaScript in the canonical shape `async () => { ... }`. The runtime can normalize some alternate
  JavaScript forms, but do not rely on that behavior. Avoid Markdown fences, imports, TypeScript annotations,
  interfaces, and `as` casts.
- The sandbox is network-isolated. Use only injected `codemode.*` helpers; direct `fetch()`, `connect()`, and external modules cannot work.
- Use exact helper and input-field names returned by `api_docs`. Sandbox helper arguments do not receive a second local
  schema-validation pass, so a misspelled field can become an omitted parameter.
- Finish within 30 seconds. A timeout does not guarantee already-dispatched helper calls were cancelled.

## Minimize calls safely

1. Before the first data call, request all planned static helper declarations together with one
   `api_docs({ functions: [...] })` call, unless those exact declarations were already retrieved in this conversation.
   Do not make one documentation call per helper. Request the full catalog only to discover a capability whose helper
   name is genuinely unknown.
2. Prefer one `execute_code` invocation only when the complete workflow comfortably fits the deadline. Split broad screens, long windows, or multi-stage reports into explicit discovery, ranking, and deepening invocations instead of forcing one oversized run.
3. Keep to no more than six independent `codemode.*` promises at once as a reliability budget, even though the runtime
   does not enforce a concurrency counter. Use batches of 4-6 for larger sets. Use `Promise.all` for required calls
   and `Promise.allSettled` for optional enrichments so they cannot erase the core result.
4. Resolve dependencies before fan-out: fetch a profile or first catalog page, inspect it, then conditionally call covered endpoints. Do not claim a coverage gate and simultaneously fire gated calls.
5. Fetch only the lenses the user requested. Do not add prices, news, ownership, daily multiples, catalogs, or all three statements to a narrow question.

## Return compact output

- Filter dates, periods, metrics, sources, and rows inside the sandbox. The MCP does not automatically truncate
  successful logs or returned values, so never emit an unfiltered full history unless the user explicitly requests an
  export.
- Emit one compact payload with `console.log(JSON.stringify(result))`, or one CSV string for an explicit export; `console.log(object)` produces `[object Object]`. Leave the async function without a return value so the MCP does not append the same payload twice.
- Before logging `Promise.allSettled` output, reduce failures to strings such as `reason instanceof Error ? reason.message : String(reason)`; raw `Error` objects stringify to `{}`.
- For large requested exports, select only the requested columns and split rows into deterministic pages or chunks across separate `execute_code` invocations. Report the chunk boundaries and never silently omit rows.
- Do not log or return filing image/PDF base64 merely to provide a link or scan a document. Prefer `sourceUrl`, `auditUrl`, or one targeted page. Keep an explicitly requested binary call isolated and warn when the MCP path is unsuitable for a large document.

## Company identity

- Pass MCP company keys as canonical `EXCHANGE_TICKER`, for example `NASDAQ_MSFT`, `NYSE_V`, or `TSX_CSU`.
- Reuse a key already established in the conversation. For an unresolved name or ticker, search `companies_list` and take its returned `companyKey`; do not construct a key from `exchangeName` or a MIC code.
- Use `company_peers({ companyKey })` for ranked peers. Do not scan `companies_list` merely to discover a comp set.
- Call `company_profile` only when the workflow needs profile fields, a coverage gate, or `terminalUrl`.

## Non-obvious schemas

- Standardized and as-reported financials: `{ metrics, data }`; values are in `data[].metricsValues[metricId]`.
- Adjusted metrics and company ratios: `{ metrics, data }`; values are in `data[].metricValues[metricId]`. Ratio metadata identifies entries with `ratioId`.
- Segments/KPIs: join `metrics[].metricId`, `segmentGroups[].metrics[].metricId`, rollups, and `data[].metricsValues` by the stable numeric `metricId`. Request both histories with `periodType: "annual,quarterly"`.
- Stock prices: `{ listingFiscalIdentifier, ticker, exchangeCode, tradingCurrency, tradingStatus, prices }`; each price is `{ date, openPrice, closePrice, volume }`. The MCP helper accepts only `companyKey`, so slice `prices` in the sandbox.
- Most paginated lists, including news, ownership, and fund-letter directories, return `{ pagination, data }`. Request
  pages with `pageNumber`; inspect `pagination.hasNextPage` before fetching another page.
- `events_calendar` is the pagination exception: it accepts `page` plus `pageSize` and returns `{ data, meta }`. Inspect
  `meta.hasMore` and use `meta.nextPage`.
- Time series are generally newest-first. Sort ascending by their documented date field before CAGR, return, or trend calculations.
- `company_earnings_summary` returns quarterly `epsActual` and `revenueActual`; it does not return estimates despite
  the helper's current short description.
- Response declarations can show example metric keys or overstate required fields. Treat financial, adjusted-metric,
  and ratio value maps as keyed maps, inspect the first live payload, and preserve absent or null fields.

## Live and account-scoped helpers

- The helper set can vary with deployment, account features, and OAuth consent. Treat `api_docs` as authoritative for
  the current session's helper names and input signatures.
- Some user-account helpers are added dynamically with `terminal_` names. Never guess a helper name or payload. Use
  the exposed type, or one targeted `api_docs({ functions: [...] })` call when a required signature is unclear.
- Keep public-company research read-only. Use an account-scoped write or delete helper only when the user explicitly
  requests that exact change and the target and payload are unambiguous.
- If a helper reports missing consent, explain the named consent group and access level. Do not work around the grant
  with a different helper.

## Catalogs and filters

- Use known, curated ratio and standardized metric IDs directly when they are present in the returned metadata. Call `ratios_list` only for an unfamiliar user-named ratio or after a known ID is absent.
- Inspect the `metrics` array returned with a statement before calling `standardized_metrics_list`. Use the catalog only for an unresolved template-specific line item.
- The MCP `company_ratios` helper does not accept `ratioId`; select the required ratios in the sandbox.
- The MCP `company_stock_prices` helper does not accept date filters; slice the nested `prices` array in the sandbox.
- Use `top_news` for a one-company or cross-company high-signal feed, importance ranges, multiple comma-separated event types, and pagination. Use `company_news` for a company-specific window longer than seven days; its `importance` filter is one exact score and each custom window is at most 31 days.

## Sources, errors, and entitlements

- If Fiscal `execute_code` is unavailable in the session, stop and say that the Fiscal.ai connector is not available. Never answer with remembered financial values.
- Link filing-backed data with `auditUrl`, falling back to `originalSourceUrl`. Use `terminalUrl` for a company-level Fiscal link.
- Never show raw `document`, `image`, API `pdfUrl`, or base64 payloads as user links. They require API authentication. Use `filing_page_image` only for a known page; use `filing_pdf` only for an explicitly requested binary that is small enough for this MCP path.
- Treat 403 as unavailable coverage or entitlement and continue with a clearly labeled partial result. Treat 429 with limited backoff; do not hammer or silently omit names.
- Never fill missing Fiscal data with remembered values or unsourced web numbers. State the gap.
