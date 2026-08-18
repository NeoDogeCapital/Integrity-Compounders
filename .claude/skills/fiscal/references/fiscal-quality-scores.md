# Fiscal Quality Scores

Read [the Fiscal MCP contract](mcp-workflow.md). Compute only the requested models and disclose their applicability; do not fetch a peer percentile study by default.

## Fetch minimally

1. Fetch `company_profile({ companyKey })` to determine reporting template and applicability.
2. Map each requested score to required inputs, then fetch only the needed annual statements and `company_ratios({ companyKey, periodType: "annual,latest" })` in one parallel fan-out.
3. Use returned statement `metrics` and ratio metadata to resolve inputs. Call a catalog only when a required input remains unresolved.
4. For peer percentiles, first call `company_peers`, then fetch ratios for 5-10 peers in batches of at most six. Deepen peers in a separate invocation with statements only if the specific score cannot be computed from ratios. Make this opt-in.

## Model rules

- Show the formula, period, exact Fiscal inputs, substitutions, and missing terms for every score.
- Respect each model’s original population. Altman variants differ for public manufacturers, private firms, and non-manufacturers; Beneish is less meaningful for financial institutions; Piotroski requires comparable year-over-year inputs.
- Treat signs consistently and preserve missing values. Do not silently coerce unavailable inputs to zero.
- Label every score as a screening signal, not a finding of fraud, insolvency, or investment merit.
- If restatements or stub periods affect inputs, flag them and avoid a false precision verdict.

## Output

Return a score table with value, threshold band, input completeness, and plain-language interpretation, followed by the two or three strongest underlying drivers. Cite filing-backed inputs with `auditUrl`. Use fiscal-adjusted-earnings-quality for GAAP/non-GAAP bridges rather than mixing that workflow into the scorecard.
