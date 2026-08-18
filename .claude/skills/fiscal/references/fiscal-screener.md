# Fiscal Screener

Read [the Fiscal MCP contract](mcp-workflow.md). Reduce the universe before fundamental calls and disclose that broad screens can consume many API calls.

## Stage the screen

Use separate discovery and fundamental passes for broad screens:

1. In the discovery invocation, page through `companies_list({ pageNumber, pageSize: 1000 })`, reading `pagination`. Apply all descriptive filters immediately: active status, pre-IPO, country, sector, industry/subIndustry, template, and available datasets. Return only candidate keys plus fields needed to explain the universe.
2. If more than 20 candidates survive, tighten the descriptive criteria or ask the user before fundamental fan-out. Do not silently choose the first 20.
3. In each fundamental invocation, fetch
   `company_ratios({ companyKey: candidate.companyKey, periodType: "latest,annual" })` for one deterministic group of
   at most six candidates. Return reduced screening fields, then continue the next group in another invocation.
4. Fetch standardized statements only when the criterion truly requires a raw line or custom calculation that ratios cannot supply. Run this as a separate pass over the ratio-screen survivors.
5. Rank first, then deepen only the top 5-10 with profiles, statements, segments, or news if requested.

## Screen accurately

- Resolve ratio fields from each response’s metadata. Use catalogs only for unfamiliar criteria.
- Normalize monetary thresholds to a stated currency and separate trading from reporting currency.
- Treat missing values as unknown, not passing or zero. Report survivor counts after each stage.
- Do not claim sector-relative valuation unless the comparison cohort is actually computed.
- Avoid formulas such as NCAV or custom quality scores unless every required statement input is available and cited.

## Output

Return the screen definition, universe and survivor counts, deterministic candidate-chunk boundaries, a ranked table,
missing-data exclusions, and key caveats. If the full requested universe cannot finish reliably, return a clearly
labeled partial screen and the exact narrowing needed; never silently omit companies.
