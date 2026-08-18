# Fiscal IR Events and Transcripts

Read [the Fiscal MCP contract](mcp-workflow.md). Separate scheduled-event questions from historical IR resources and
fetch only the requested surface.

## Upcoming and past event dates

- Use `events_calendar` only when it appears in the live `api_docs` catalog. It is an optional, entitlement-gated
  helper and may not be present in every deployment or session.
- Bundle multiple known company keys into one comma-separated `companyKey` value. Do not make one calendar call per
  company.
- Use `startDate` and `endDate` for an exact window and one `status` only when the user asks for confirmed, estimated,
  projected, or reported events specifically.
- This helper paginates with `page` plus `pageSize`, not `pageNumber`, and returns `{ data, meta }`. Supply both when
  paging, inspect `meta.hasMore`, and continue with `meta.nextPage`. Narrow a result that would exceed 1,000 rows.
- Preserve the returned status. A projected window is not a confirmed earnings date.

## Historical IR resources

1. Call `company_ir_events({ companyKey })` once. Do not pre-gate this helper on
   `company_profile.availableDatasets`; the public profile's dataset list does not advertise IR coverage.
2. Group its flat resource rows by
   `(eventType, fiscalYear, fiscalQuarter)`; rows in the same group belong to one event.
3. Use each row according to `resourceType`:
   - `document`: identify the interim report, annual report, slide deck, or press release from `role`.
     `resourceId` is a filing ID. Use it with a filing helper only when the user explicitly needs source reading;
     do not expose the row's authenticated `url` as a public link.
   - `transcript`: pass the row's `resourceId` as `eventKey` to
     `company_ir_events_transcript({ companyKey, eventKey })`.
   - `audio`: report its availability, but do not fetch it through MCP or present its authenticated stream URL as a
     public link.

## Transcript analysis

- Select events from `company_ir_events` before fetching transcripts. For “latest call,” choose the newest event group
  that actually contains a `resourceType: "transcript"` row; a newer document-only event does not prove that its
  transcript is available. Fetch only the requested events, in batches of at most six, and reduce each transcript to
  the requested topics, speakers, quotations, Q&A exchanges, or timestamps inside the same sandbox invocation. Do not
  emit or refetch an entire transcript unless the user explicitly requests it.
- `speakers` is an array. Build a map keyed by each row's `speaker` number before resolving the `speaker` values on
  paragraphs or sentences; do not index the array as though speaker numbers were array positions.
- For Q&A-only analysis, find the `sections` row whose `sectionType` is `qa`, then keep paragraphs or sentences whose
  timestamps overlap that section. Preserve the speaker name, role, speaker type, and timestamp when they support the
  answer.
- Quote only text present in the transcript. Keep excerpts short and label ambiguous or unresolved attribution
  instead of guessing a speaker.
- Distinguish management statements from analyst questions and your own interpretation. Do not turn management
  commentary into company guidance or analyst consensus unless the response explicitly identifies it that way.

## Output

For calendars, return event date or date window, status, timing, fiscal period, and company. For historical events,
return the event identity, call date when known, available resource types, and the requested transcript findings.
State missing coverage, missing transcripts, entitlement failures, and whether each calendar date is confirmed,
estimated, projected, or reported. Link filing-backed evidence only through public source or audit links returned by
the relevant Fiscal helper.
