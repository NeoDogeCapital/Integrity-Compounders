# Financial-model row template — STANDARD

Authoritative, fixed row structure pulled from `standardized_metrics_list` (templateType: `standard`). LOAD this skeleton and FILL values from `company_financials_standardized` keyed by metric id — do NOT re-derive the structure at runtime. Rows are in canonical order; **[T]** marks a subtotal with its build-up (operands use ids with the statement prefix stripped). If a company reports an id not listed here, append it under the nearest group and flag it; if a listed id is absent for a company, render the row as n/a.

## Income Statement (25 rows)
1. `income_statement_total_revenues` — Total Revenues
2. `income_statement_cost_of_sales` — Cost of Sales
3. `income_statement_gross_profit` **[T]** — Gross Profit  _= +total_revenues −cost_of_sales_
4. `income_statement_selling_general_and_administrative_expenses` — Selling, General & Administrative Expenses
5. `income_statement_depreciation_and_amortization_expenses` — Depreciation & Amortization Expenses
6. `income_statement_research_and_development_expenses` — Research & Development Expenses
7. `exploration_expenses` — Exploration Expenses
8. `income_statement_other_operating_expenses` — Other Operating Expenses
9. `income_statement_operating_profit` **[T]** — Operating Profit  _= +gross_profit −selling_general_and_administrative_expenses −depreciation_and_amortization_expenses −research_and_development_expenses −other_operating_expenses −exploration_expenses_
10. `income_statement_interest_income` — Interest and Investment Income
11. `income_statement_interest_expense` — Interest Expense
12. `income_statement_non_operating_income` — Non-Operating Income
13. `income_statement_non_operating_income_or_expense` **[T]** — Total Non-Operating Income  _= +interest_income +interest_expense +non_operating_income_
14. `income_statement_income_before_provision_for_income_taxes` **[T]** — Income Before Provision for Income Taxes  _= +operating_profit +non_operating_income_or_expense_
15. `income_statement_provision_for_income_taxes` — Provision for Income Taxes
16. `income_statement_consolidated_net_income` **[T]** — Consolidated Net Income  _= +income_before_provision_for_income_taxes −provision_for_income_taxes_
17. `income_statement_net_income_attributable_to_minority_interests_and_other` — Net Income Attributable to Minority Interests and Other
18. `income_statement_net_income_attributable_to_preferred_dividends` — Net Income Attributable to Preferred Dividends
19. `income_statement_net_income_attributable_to_discontinued_operations` — Net Income Attributable to Discontinued Operations
20. `income_statement_net_income_attributable_to_common_shareholders` **[T]** — Net Income Attributable to Common Shareholders  _= +consolidated_net_income −net_income_attributable_to_minority_interests_and_other −net_income_attributable_to_preferred_dividends +net_income_attributable_to_discontinued_operations_
21. `income_statement_basic_eps` — Basic EPS
22. `income_statement_diluted_eps` — Diluted EPS
23. `income_statement_basic_weighted_average_shares_outstanding` — Basic Weighted Average Shares Outstanding
24. `income_statement_diluted_weighted_average_shares_outstanding` — Diluted Weighted Average Shares Outstanding
25. `shares_outstanding` — Shares Outstanding  _(group: Shares)_

## Balance Sheet (38 rows)
1. `balance_sheet_cash_and_cash_equivalents` — Cash and Cash Equivalents  _(group: Assets)_
2. `balance_sheet_short_term_investments` — Short-Term Investments  _(group: Assets)_
3. `balance_sheet_total_cash_and_cash_equivalents` **[T]** — Total Cash and Cash Equivalents  _(group: Assets)_  _= +cash_and_cash_equivalents +short_term_investments_
4. `balance_sheet_accounts_receivable` — Accounts Receivable  _(group: Assets)_
5. `balance_sheet_other_receivables` — Other Receivables  _(group: Assets)_
6. `balance_sheet_total_trade_receivables` **[T]** — Total Trade Receivables  _(group: Assets)_  _= +accounts_receivable +other_receivables_
7. `balance_sheet_inventories` — Inventories  _(group: Assets)_
8. `balance_sheet_other_current_assets` — Other Current Assets  _(group: Assets)_
9. `balance_sheet_total_current_assets` **[T]** — Total Current Assets  _(group: Assets)_  _= +total_cash_and_cash_equivalents +total_trade_receivables +inventories +other_current_assets_
10. `balance_sheet_net_property_plant_and_equipment` **[T]** — Net Property, Plant & Equipment  _(group: Assets)_  _= +gross_property_plant_and_equipment −less_accumulated_depreciation_
11. `balance_sheet_net_intangible_assets` — Net Intangible Assets  _(group: Assets)_
12. `balance_sheet_goodwill` — Goodwill  _(group: Assets)_
13. `balance_sheet_long_term_investments` — Long-Term Investments  _(group: Assets)_
14. `balance_sheet_other_long_term_assets` — Other Long-Term Assets  _(group: Assets)_
15. `balance_sheet_total_assets` **[T]** — Total Assets  _(group: Assets)_  _= +total_current_assets +net_property_plant_and_equipment +net_intangible_assets +goodwill +long_term_investments +other_long_term_assets_
16. `balance_sheet_accounts_payable` — Accounts Payable  _(group: Liabilities)_
17. `balance_sheet_accrued_expenses` — Accrued Expenses  _(group: Liabilities)_
18. `balance_sheet_short_term_debt` — Short-Term Debt  _(group: Liabilities)_
19. `balance_sheet_current_portion_of_long_term_debt` — Current Portion of Long-Term Debt  _(group: Liabilities)_
20. `balance_sheet_current_portion_of_leases` — Current Portion of Leases  _(group: Liabilities)_
21. `balance_sheet_unearned_revenue` — Unearned Revenue  _(group: Liabilities)_
22. `balance_sheet_other_current_liabilities` — Other Current Liabilities  _(group: Liabilities)_
23. `balance_sheet_total_current_liabilities` **[T]** — Total Current Liabilities  _(group: Liabilities)_  _= +accounts_payable +accrued_expenses +short_term_debt +current_portion_of_long_term_debt +current_portion_of_leases +unearned_revenue +other_current_liabilities_
24. `balance_sheet_long_term_debt` — Long-Term Debt  _(group: Liabilities)_
25. `balance_sheet_leases` — Leases  _(group: Liabilities)_
26. `balance_sheet_other_long_term_liabilities` — Other Long-Term Liabilities  _(group: Liabilities)_
27. `balance_sheet_total_long_term_liabilities` **[T]** — Total Long-Term Liabilities  _(group: Liabilities)_  _= +long_term_debt +leases +other_long_term_liabilities_
28. `balance_sheet_total_liabilities` **[T]** — Total Liabilities  _(group: Liabilities)_  _= +total_current_liabilities +total_long_term_liabilities_
29. `balance_sheet_preferred_stock` — Preferred Stock  _(group: Equity)_
30. `balance_sheet_common_stock` — Common Stock  _(group: Equity)_
31. `balance_sheet_treasury_stock` — Treasury Stock  _(group: Equity)_
32. `balance_sheet_additional_paid_in_capital` — Additional Paid-in Capital  _(group: Equity)_
33. `balance_sheet_accumulated_other_comprehensive_income` — Accumulated Other Comprehensive Income  _(group: Equity)_
34. `balance_sheet_retained_earnings` — Retained Earnings  _(group: Equity)_
35. `balance_sheet_total_common_shareholders_equity` **[T]** — Total Common Shareholders' Equity  _(group: Equity)_  _= +preferred_stock +common_stock +treasury_stock +additional_paid_in_capital +accumulated_other_comprehensive_income +retained_earnings_
36. `balance_sheet_minority_interests_and_other` — Minority Interests and Other  _(group: Equity)_
37. `balance_sheet_total_shareholders_equity` **[T]** — Total Shareholders' Equity  _(group: Equity)_  _= +total_common_shareholders_equity +minority_interests_and_other_
38. `balance_sheet_total_liabilities_and_shareholders_equity` **[T]** — Total Liabilities and Shareholders' Equity  _(group: Equity)_  _= +total_liabilities +total_shareholders_equity_

## Cash Flow Statement (42 rows)
1. `cash_flow_statement_net_income` — Net Income  _(group: Operating Activities)_
2. `cash_flow_statement_depreciation_and_amortization` — Depreciation & Amortization  _(group: Operating Activities)_
3. `cash_flow_statement_share_based_compensation_expense` — Share-Based Compensation Expense  _(group: Operating Activities)_
4. `cash_flow_statement_other_adjustments` — Other Adjustments  _(group: Operating Activities)_
5. `cash_flow_statement_changes_in_trade_receivables` — Changes in Trade Receivables  _(group: Operating Activities)_
6. `cash_flow_statement_changes_in_inventories` — Changes in Inventories  _(group: Operating Activities)_
7. `cash_flow_statement_changes_in_accounts_payable` — Changes in Accounts Payable  _(group: Operating Activities)_
8. `cash_flow_statement_changes_in_accrued_expenses` — Changes in Accrued Expenses  _(group: Operating Activities)_
9. `cash_flow_statement_changes_in_income_taxes_payable` — Changes in Income Taxes Payable  _(group: Operating Activities)_
10. `cash_flow_statement_changes_in_unearned_revenue` — Changes in Unearned Revenue  _(group: Operating Activities)_
11. `cash_flow_statement_changes_in_other_operating_activities` — Changes in Other Operating Activities  _(group: Operating Activities)_
12. `cash_flow_statement_cash_from_operating_activities` **[T]** — Cash from Operating Activities  _(group: Operating Activities)_  _= +net_income +depreciation_and_amortization +share_based_compensation_expense +other_adjustments +changes_in_trade_receivables +changes_in_inventories +changes_in_accounts_payable +changes_in_accrued_expenses +changes_in_income_taxes_payable +changes_in_unearned_revenue +changes_in_other_operating_activities_
13. `cash_flow_statement_purchases_of_property_plant_and_equipment` — Capital Expenditure  _(group: Investing Activities)_
14. `cash_flow_statement_proceeds_from_sale_of_property_plant_and_equipment` — Proceeds from Sale of Property, Plant & Equipment  _(group: Investing Activities)_
15. `cash_flow_statement_purchases_of_intangible_assets` — Purchases of Intangible Assets  _(group: Investing Activities)_
16. `cash_flow_statement_proceeds_from_sale_of_intangible_assets` — Proceeds from Sale of Intangible Assets  _(group: Investing Activities)_
17. `cash_flow_statement_purchases_of_investments` — Purchases of Investments  _(group: Investing Activities)_
18. `cash_flow_statement_proceeds_from_sale_of_investments` — Proceeds from Sale of Investments  _(group: Investing Activities)_
19. `cash_flow_statement_payments_for_business_acquisitions` — Payments for Business Acquisitions  _(group: Investing Activities)_
20. `cash_flow_statement_proceeds_from_business_divestments` — Proceeds from Business Divestments  _(group: Investing Activities)_
21. `cash_flow_statement_other_investing_activities` — Other Investing Activities  _(group: Investing Activities)_
22. `cash_flow_statement_cash_from_investing_activities` **[T]** — Cash from Investing Activities  _(group: Investing Activities)_  _= +purchases_of_property_plant_and_equipment +proceeds_from_sale_of_property_plant_and_equipment +purchases_of_intangible_assets +proceeds_from_sale_of_intangible_assets +purchases_of_investments +proceeds_from_sale_of_investments +payments_for_business_acquisitions +proceeds_from_business_divestments +other_investing_activities_
23. `cash_flow_statement_issuance_of_short_term_debt` — Issuance of Short-Term Debt  _(group: Financing Activities)_
24. `cash_flow_statement_repayments_of_short_term_debt` — Repayments of Short-Term Debt  _(group: Financing Activities)_
25. `cash_flow_statement_net_issuance_or_repayments_of_short_term_debt` **[T]** — Net Issuance / (Repayments) of Short-Term Debt  _(group: Financing Activities)_  _= +issuance_of_short_term_debt +repayments_of_short_term_debt_
26. `cash_flow_statement_issuance_of_long_term_debt` — Issuance of Long-Term Debt  _(group: Financing Activities)_
27. `cash_flow_statement_repayments_of_long_term_debt` — Repayments of Long-Term Debt  _(group: Financing Activities)_
28. `cash_flow_statement_net_issuance_or_repayments_of_long_term_debt` **[T]** — Net Issuance / (Repayments) of Long-Term Debt  _(group: Financing Activities)_  _= +issuance_of_long_term_debt +repayments_of_long_term_debt_
29. `cash_flow_statement_issuance_of_common_shares` — Issuance of Common Shares  _(group: Financing Activities)_
30. `cash_flow_statement_repurchases_of_common_shares` — Repurchases of Common Shares  _(group: Financing Activities)_
31. `cash_flow_statement_net_issuance_or_repurchases_of_common_shares` **[T]** — Net Issuance / (Repurchases) of Common Shares  _(group: Financing Activities)_  _= +issuance_of_common_shares +repurchases_of_common_shares_
32. `cash_flow_statement_issuance_of_preferred_shares` — Issuance of Preferred Shares  _(group: Financing Activities)_
33. `cash_flow_statement_repurchases_of_preferred_shares` — Repurchases of Preferred Shares  _(group: Financing Activities)_
34. `cash_flow_statement_net_issuance_or_repurchases_of_preferred_shares` **[T]** — Net Issuance / (Repurchases) of Preferred Shares  _(group: Financing Activities)_  _= +issuance_of_preferred_shares +repurchases_of_preferred_shares_
35. `cash_flow_statement_common_share_dividends_paid` — Common Share Dividends Paid  _(group: Financing Activities)_
36. `cash_flow_statement_preferred_share_dividends_paid` — Preferred Share Dividends Paid  _(group: Financing Activities)_
37. `cash_flow_statement_other_financing_activities` — Other Financing Activities  _(group: Financing Activities)_
38. `cash_flow_statement_cash_from_financing_activities` **[T]** — Cash from Financing Activities  _(group: Financing Activities)_  _= +net_issuance_or_repayments_of_short_term_debt +net_issuance_or_repayments_of_long_term_debt +net_issuance_or_repurchases_of_common_shares +net_issuance_or_repurchases_of_preferred_shares +common_share_dividends_paid +preferred_share_dividends_paid +other_financing_activities_
39. `cash_flow_statement_effect_of_exchange_rate_changes_on_cash_and_cash_equivalents` — Effect of Exchange Rate Changes on Cash and Cash Equivalents  _(group: Net Change in Cash)_
40. `cash_flow_statement_increase_or_decrease_in_cash_cash_equivalents_and_restricted_cash` **[T]** — Increase / (Decrease) in Cash, Cash Equivalents and Restricted Cash  _(group: Net Change in Cash)_  _= +cash_from_operating_activities +cash_from_investing_activities +cash_from_financing_activities +effect_of_exchange_rate_changes_on_cash_and_cash_equivalents_
41. `cash_flow_statement_cash_cash_equivalents_and_restricted_cash_at_beginning_of_period` — Cash, Cash Equivalents and Restricted Cash at Beginning of Period  _(group: Net Change in Cash)_
42. `cash_flow_statement_cash_cash_equivalents_and_restricted_cash_at_end_of_period` **[T]** — Cash, Cash Equivalents and Restricted Cash at End of Period  _(group: Net Change in Cash)_  _= +cash_cash_equivalents_and_restricted_cash_at_beginning_of_period +increase_or_decrease_in_cash_cash_equivalents_and_restricted_cash_
