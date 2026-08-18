# Fiscal Valuation

Read [the Fiscal MCP contract](mcp-workflow.md). Choose the method first, then fetch only its required inputs.

## Fetch by method

Use one subject invocation, then separate peer deepening when required:

- Always fetch `company_profile` when template, currency, pre-IPO status, or `terminalUrl` is needed, plus `company_ratios({ companyKey, periodType: "latest,annual" })` for current capitalization and core ratios.
- Reverse/explicit DCF: add the annual cash-flow statement and only the income/balance-sheet lines needed for the selected cash-flow definition, net debt, and reinvestment assumptions.
- Historical-multiple valuation: add one requested `company_daily_ratios` series; do not fetch a daily multiple for every valuation.
- Comparable valuation: after the subject payload, call `company_peers`, select at most five approved peers, and fetch
  their ratios in a later invocation. Fetch comparability statements in another invocation only for the peers that
  survive the ratio comparison.
- Per-share bridge: add `company_shares_outstanding` only when diluted share count is not already usable.
- Adjusted-earnings valuation: add adjusted metrics only when requested and covered.

## Model

- Separate reported historical inputs, derived values, and assumptions.
- State the cash-flow definition and preserve statement signs. Do not mix levered and unlevered cash flows with the wrong discount rate.
- For reverse DCF, solve for the growth/margin/reinvestment assumption implied by current enterprise or equity value.
- For explicit DCF, show forecast horizon, terminal method, discount rate, and net-debt/equity bridge.
- For multiples, compare like templates and fiscal periods; use median and range, not a single peer outlier.
- For IRR, state entry value, operating assumptions, exit multiple/value, distributions, and horizon.

## Output

Lead with the valuation range or implied expectation, then show a compact assumption table and sensitivity analysis.
Cite historical filing inputs with `auditUrl`. Unless a live helper explicitly returns a forward field, forecast
values are user or scenario assumptions; never derive analyst consensus or price targets from historical statements,
ratios, or news.
