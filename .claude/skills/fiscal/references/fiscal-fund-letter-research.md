# Fiscal Fund-Letter Research

Read [the Fiscal MCP contract](mcp-workflow.md). Start from the entity the user names and deepen only the letters or
theses needed for the question.

## Choose the entry point

- One company: call `company_fund_letters({ companyKey })` once. It returns the complete company feed, not a paginated
  list, so reduce its `theses` in the sandbox by period, investor, stance, relationship, or requested topic before
  logging. Use the returned stance, conviction, relationship, position sizing, thesis, risks, catalysts, valuation,
  management commentary, source quote, investor, fund, and `letterId` only when present.
- One calendar period: call `fund_letters({ year, quarter?, investorId?, fundId?, pageNumber?, pageSize? })`. `year`
  is required and must be 2020 or later.
- One investment firm: use `fund_letter_investors({ pageNumber?, pageSize? })` only to discover an unknown
  `investorId`, then call `fund_letter_investor({ investorId })` for its profile, funds, and complete letter feed.
- Discover covered companies: use `fund_letter_companies({ pageNumber?, pageSize? })`.
- One selected letter: call `fund_letter({ letterId })` for the full extracted content. Use `fund_letter_pdf` only
  when that content is insufficient and the user needs the primary document; keep the binary call isolated.

Inspect `pagination.hasNextPage` on directory and period-list responses before requesting another page.
`company_fund_letters` and the two detail helpers are not paginated. Reuse identifiers returned by earlier calls and
never construct `fscl_document_`, `fscl_investor_`, or `fscl_fund_` identifiers. When selecting from an investor's
feed, do not assume the newest letter contains company theses; choose the letter that matches the requested period,
fund, or topic and name the fund in the answer.

## Analyze

- Separate the letter's own wording from Fiscal's structured extraction and from your synthesis. `sourceQuote` is the
  representative verbatim excerpt; fields such as `thesisSummary`, `riskSummary`, and `valuationSummary` are
  structured summaries and must not be presented as direct quotations.
- Preserve the letter's reporting period. Do not treat a historical position, stance, or valuation as current.
- Treat each letter as one investor's dated view, not current holdings, analyst consensus, or a fact about the
  company. A later letter can change or supersede the earlier view.
- For “how has the view changed,” compare the same investor and fund across reporting periods first. Then summarize
  cross-investor changes separately; an aggregate stance shift can reflect a different set of writers rather than an
  existing investor changing its mind.
- Compare several investors only on matching concepts actually disclosed; absence of a position size or valuation is
  missing data, not zero conviction.
- Use short source excerpts only when they materially support the answer. Prefer paraphrase for broad synthesis.

## Output

Lead with the requested investor view, change, disagreement, or cross-letter pattern. Identify investor, fund,
reporting period, stance, relationship, and disclosed sizing when available. Date every view and identify which claims
are quoted, structured extraction, or your synthesis. Link the relevant source only when a public source URL is
returned. Distinguish 403 entitlement failures from 404 or empty coverage, and state pagination, coverage, and recency
limitations without turning a missing thesis into a negative investment view.
