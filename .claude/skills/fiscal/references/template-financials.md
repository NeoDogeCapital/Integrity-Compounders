# Financial-model row template — FINANCIALS

Authoritative, fixed row structure pulled from `standardized_metrics_list` (templateType: `financials`). LOAD this skeleton and FILL values from `company_financials_standardized` keyed by metric id — do NOT re-derive the structure at runtime. Rows are in canonical order; **[T]** marks a subtotal with its build-up (operands use ids with the statement prefix stripped). If a company reports an id not listed here, append it under the nearest group and flag it; if a listed id is absent for a company, render the row as n/a.

## Income Statement (21 rows)
1. `income_statement_net_interest_income` — Net Interest Income
2. `income_statement_non_interest_income` — Non-Interest Income
3. `income_statement_total_revenues_before_provision_for_credit_losses` **[T]** — Total Revenues Before Provision for Credit Losses  _= +net_interest_income +non_interest_income_
4. `income_statement_provision_for_credit_losses` — Provision for Credit Losses
5. `income_statement_total_revenues_after_provision_for_credit_losses` **[T]** — Total Revenues After Provision for Credit Losses  _= +total_revenues_before_provision_for_credit_losses −provision_for_credit_losses_
6. `income_statement_compensation_expenses` — Compensation Expenses
7. `income_statement_selling_general_and_administrative_expenses` — Selling, General & Administrative Expenses
8. `income_statement_other_non_interest_expenses` — Other Non-Interest Expenses
9. `income_statement_total_non_interest_expense` **[T]** — Total Non-Interest Expense  _= +compensation_expenses +selling_general_and_administrative_expenses +other_non_interest_expenses_
10. `income_statement_income_before_provision_for_income_taxes` **[T]** — Income Before Provision for Income Taxes  _= +total_revenues_after_provision_for_credit_losses −total_non_interest_expense_
11. `income_statement_provision_for_income_taxes` — Provision for Income Taxes
12. `income_statement_consolidated_net_income` **[T]** — Consolidated Net Income  _= +income_before_provision_for_income_taxes −provision_for_income_taxes_
13. `income_statement_net_income_attributable_to_minority_interests_and_other` — Net Income Attributable to Minority Interests and Other
14. `income_statement_net_income_attributable_to_preferred_dividends` — Net Income Attributable to Preferred Dividends
15. `income_statement_net_income_attributable_to_discontinued_operations` — Net Income Attributable to Discontinued Operations
16. `income_statement_net_income_attributable_to_common_shareholders` **[T]** — Net Income Attributable to Common Shareholders  _= +consolidated_net_income −net_income_attributable_to_minority_interests_and_other −net_income_attributable_to_preferred_dividends +net_income_attributable_to_discontinued_operations_
17. `income_statement_basic_eps` — Basic EPS
18. `income_statement_diluted_eps` — Diluted EPS
19. `income_statement_basic_weighted_average_shares_outstanding` — Basic Weighted Average Shares Outstanding
20. `income_statement_diluted_weighted_average_shares_outstanding` — Diluted Weighted Average Shares Outstanding
21. `shares_outstanding` — Shares Outstanding  _(group: Shares)_

## Balance Sheet (36 rows)
1. `balance_sheet_cash_and_cash_equivalents` — Cash and Cash Equivalents  _(group: Assets)_
2. `balance_sheet_securities_and_investments` — Securities and Investments  _(group: Assets)_
3. `balance_sheet_short_term_interbank_lending_and_reverse_repurchase_agreements` — Short-Term Interbank Lending and Reverse Repurchase Agreements  _(group: Assets)_
4. `balance_sheet_trading_assets` — Trading Assets  _(group: Assets)_
5. `balance_sheet_other_earning_assets` — Other Earning Assets  _(group: Assets)_
6. `balance_sheet_gross_loans` — Gross Loans  _(group: Assets)_
7. `balance_sheet_less_allowance_for_loan_losses` — Allowance for Loan Losses  _(group: Assets)_
8. `balance_sheet_net_loans` **[T]** — Net Loans  _(group: Assets)_  _= +gross_loans +less_allowance_for_loan_losses_
9. `balance_sheet_net_property_plant_and_equipment` **[T]** — Net Property, Plant & Equipment  _(group: Assets)_  _= +gross_property_plant_and_equipment −less_accumulated_depreciation_
10. `balance_sheet_accrued_interest_and_accounts_receivable` — Accrued Interest and Accounts Receivable  _(group: Assets)_
11. `balance_sheet_net_intangible_assets` — Net Intangible Assets  _(group: Assets)_
12. `balance_sheet_goodwill` — Goodwill  _(group: Assets)_
13. `balance_sheet_long_term_investments` — Long-Term Investments  _(group: Assets)_
14. `balance_sheet_other_non_earning_assets` — Other Non-Earning Assets  _(group: Assets)_
15. `balance_sheet_total_assets` **[T]** — Total Assets  _(group: Assets)_  _= +cash_and_cash_equivalents +securities_and_investments +short_term_interbank_lending_and_reverse_repurchase_agreements +trading_assets +other_earning_assets +net_loans +net_property_plant_and_equipment +accrued_interest_and_accounts_receivable +net_intangible_assets +goodwill +long_term_investments +other_non_earning_assets_
16. `balance_sheet_interest_bearing_deposits` — Interest-bearing deposits  _(group: Liabilities)_
17. `balance_sheet_noninterest_bearing_deposits` — Noninterest-bearing deposits  _(group: Liabilities)_
18. `balance_sheet_total_deposits` **[T]** — Total Deposits  _(group: Liabilities)_  _= +interest_bearing_deposits +noninterest_bearing_deposits_
19. `balance_sheet_short_term_interbank_borrowing_and_repurchase_agreements` — Short-Term Interbank Borrowing and Repurchase Agreements  _(group: Liabilities)_
20. `balance_sheet_short_term_borrowings` — Short-Term Borrowings  _(group: Liabilities)_
21. `balance_sheet_trading_liabilities` — Trading Liabilities  _(group: Liabilities)_
22. `balance_sheet_accounts_payable` — Accounts Payable  _(group: Liabilities)_
23. `balance_sheet_accrued_expenses` — Accrued Expenses  _(group: Liabilities)_
24. `balance_sheet_long_term_debt` — Long-Term Debt  _(group: Liabilities)_
25. `balance_sheet_other_liabilities` — Other Liabilities  _(group: Liabilities)_
26. `balance_sheet_total_liabilities` **[T]** — Total Liabilities  _(group: Liabilities)_  _= +total_deposits +short_term_interbank_borrowing_and_repurchase_agreements +short_term_borrowings +trading_liabilities +accounts_payable +accrued_expenses +long_term_debt +other_liabilities_
27. `balance_sheet_preferred_stock` — Preferred Stock  _(group: Equity)_
28. `balance_sheet_common_stock` — Common Stock  _(group: Equity)_
29. `balance_sheet_treasury_stock` — Treasury Stock  _(group: Equity)_
30. `balance_sheet_additional_paid_in_capital` — Additional Paid-in Capital  _(group: Equity)_
31. `balance_sheet_accumulated_other_comprehensive_income` — Accumulated Other Comprehensive Income  _(group: Equity)_
32. `balance_sheet_retained_earnings` — Retained Earnings  _(group: Equity)_
33. `balance_sheet_total_common_shareholders_equity` **[T]** — Total Common Shareholders' Equity  _(group: Equity)_  _= +preferred_stock +common_stock +treasury_stock +additional_paid_in_capital +accumulated_other_comprehensive_income +retained_earnings_
34. `balance_sheet_minority_interests_and_other` — Minority Interests and Other  _(group: Equity)_
35. `balance_sheet_total_shareholders_equity` **[T]** — Total Shareholders' Equity  _(group: Equity)_  _= +total_common_shareholders_equity +minority_interests_and_other_
36. `balance_sheet_total_liabilities_and_shareholders_equity` **[T]** — Total Liabilities and Shareholders' Equity  _(group: Equity)_  _= +total_liabilities +total_shareholders_equity_

## Cash Flow Statement (47 rows)
1. `cash_flow_statement_net_income` — Net Income  _(group: Operating Activities)_
2. `cash_flow_statement_depreciation_and_amortization` — Depreciation & Amortization  _(group: Operating Activities)_
3. `cash_flow_statement_provision_for_credit_losses` — Provision for Credit Losses  _(group: Operating Activities)_
4. `cash_flow_statement_share_based_compensation_expense` — Share-Based Compensation Expense  _(group: Operating Activities)_
5. `cash_flow_statement_net_change_in_loans_held_for_sale` — Net Change in Loans Held-for-Sale  _(group: Operating Activities)_
6. `cash_flow_statement_other_adjustments` — Other Adjustments  _(group: Operating Activities)_
7. `cash_flow_statement_changes_in_trading_assets` — Changes in Trading Assets  _(group: Operating Activities)_
8. `cash_flow_statement_changes_in_securities_borrowed` — Changes in Securities Borrowed  _(group: Operating Activities)_
9. `cash_flow_statement_changes_in_accrued_interest_and_accounts_receivable` — Changes in Accrued Interest and Accounts Receivable  _(group: Operating Activities)_
10. `cash_flow_statement_changes_in_trading_liabilities` — Changes in Trading Liabilities  _(group: Operating Activities)_
11. `cash_flow_statement_changes_in_accounts_payable` — Changes in Accounts Payable  _(group: Operating Activities)_
12. `cash_flow_statement_changes_in_accrued_expenses` — Changes in Accrued Expenses  _(group: Operating Activities)_
13. `cash_flow_statement_changes_in_other_operating_activities` — Changes in Other Operating Activities  _(group: Operating Activities)_
14. `cash_flow_statement_cash_from_operating_activities` **[T]** — Cash from Operating Activities  _(group: Operating Activities)_  _= +net_income +depreciation_and_amortization +provision_for_credit_losses +share_based_compensation_expense +net_change_in_loans_held_for_sale +other_adjustments +changes_in_trading_assets +changes_in_securities_borrowed +changes_in_accrued_interest_and_accounts_receivable +changes_in_trading_liabilities +changes_in_accounts_payable +changes_in_accrued_expenses +changes_in_other_operating_activities_
15. `cash_flow_statement_net_change_in_short_term_interbank_lending_and_reverse_repurchase_agreements` — Net Change in Short-Term Interbank Lending and Reverse Repurchase Agreements  _(group: Investing Activities)_
16. `cash_flow_statement_net_change_in_loans_held_for_investment` — Net Change in Loans Held-for-Investment  _(group: Investing Activities)_
17. `cash_flow_statement_net_change_in_securities_and_investments` — Net Change in Securities and Investments  _(group: Investing Activities)_
18. `cash_flow_statement_payments_for_business_acquisitions` — Payments for Business Acquisitions  _(group: Investing Activities)_
19. `cash_flow_statement_proceeds_from_business_divestments` — Proceeds from Business Divestments  _(group: Investing Activities)_
20. `cash_flow_statement_purchases_of_property_plant_and_equipment` — Capital Expenditure  _(group: Investing Activities)_
21. `cash_flow_statement_purchases_of_intangible_assets` — Purchases of Intangible Assets  _(group: Investing Activities)_
22. `cash_flow_statement_proceeds_from_sale_of_property_plant_and_equipment` — Proceeds from Sale of Property, Plant & Equipment  _(group: Investing Activities)_
23. `cash_flow_statement_proceeds_from_sale_of_intangible_assets` — Proceeds from Sale of Intangible Assets  _(group: Investing Activities)_
24. `cash_flow_statement_other_investing_activities` — Other Investing Activities  _(group: Investing Activities)_
25. `cash_flow_statement_cash_from_investing_activities` **[T]** — Cash from Investing Activities  _(group: Investing Activities)_  _= +net_change_in_short_term_interbank_lending_and_reverse_repurchase_agreements +net_change_in_loans_held_for_investment +net_change_in_securities_and_investments +payments_for_business_acquisitions +proceeds_from_business_divestments +purchases_of_property_plant_and_equipment +proceeds_from_sale_of_property_plant_and_equipment +purchases_of_intangible_assets +proceeds_from_sale_of_intangible_assets +other_investing_activities_
26. `cash_flow_statement_net_change_in_deposits` — Net Change in Deposits  _(group: Financing Activities)_
27. `cash_flow_statement_net_change_in_short_term_interbank_borrowing_and_repurchase_agreements` — Net Change in Short-Term Interbank Borrowing and Repurchase Agreements  _(group: Financing Activities)_
28. `cash_flow_statement_issuance_of_short_term_debt` — Issuance of Short-Term Debt  _(group: Financing Activities)_
29. `cash_flow_statement_repayments_of_short_term_debt` — Repayments of Short-Term Debt  _(group: Financing Activities)_
30. `cash_flow_statement_net_issuance_or_repayments_of_short_term_debt` **[T]** — Net Issuance / (Repayments) of Short-Term Debt  _(group: Financing Activities)_  _= +issuance_of_short_term_debt +repayments_of_short_term_debt_
31. `cash_flow_statement_issuance_of_long_term_debt` — Issuance of Long-Term Debt  _(group: Financing Activities)_
32. `cash_flow_statement_repayments_of_long_term_debt` — Repayments of Long-Term Debt  _(group: Financing Activities)_
33. `cash_flow_statement_net_issuance_or_repayments_of_long_term_debt` **[T]** — Net Issuance / (Repayments) of Long-Term Debt  _(group: Financing Activities)_  _= +issuance_of_long_term_debt +repayments_of_long_term_debt_
34. `cash_flow_statement_issuance_of_common_shares` — Issuance of Common Shares  _(group: Financing Activities)_
35. `cash_flow_statement_repurchases_of_common_shares` — Repurchases of Common Shares  _(group: Financing Activities)_
36. `cash_flow_statement_net_issuance_or_repurchases_of_common_shares` **[T]** — Net Issuance / (Repurchases) of Common Shares  _(group: Financing Activities)_  _= +issuance_of_common_shares +repurchases_of_common_shares_
37. `cash_flow_statement_issuance_of_preferred_shares` — Issuance of Preferred Shares  _(group: Financing Activities)_
38. `cash_flow_statement_repurchases_of_preferred_shares` — Repurchases of Preferred Shares  _(group: Financing Activities)_
39. `cash_flow_statement_net_issuance_or_repurchases_of_preferred_shares` **[T]** — Net Issuance / (Repurchases) of Preferred Shares  _(group: Financing Activities)_  _= +issuance_of_preferred_shares +repurchases_of_preferred_shares_
40. `cash_flow_statement_common_share_dividends_paid` — Common Share Dividends Paid  _(group: Financing Activities)_
41. `cash_flow_statement_preferred_share_dividends_paid` — Preferred Share Dividends Paid  _(group: Financing Activities)_
42. `cash_flow_statement_other_financing_activities` — Other Financing Activities  _(group: Financing Activities)_
43. `cash_flow_statement_cash_from_financing_activities` **[T]** — Cash from Financing Activities  _(group: Financing Activities)_  _= +net_change_in_deposits +net_change_in_short_term_interbank_borrowing_and_repurchase_agreements +net_issuance_or_repayments_of_short_term_debt +net_issuance_or_repayments_of_long_term_debt +net_issuance_or_repurchases_of_common_shares +net_issuance_or_repurchases_of_preferred_shares +common_share_dividends_paid +preferred_share_dividends_paid +other_financing_activities_
44. `cash_flow_statement_effect_of_exchange_rate_changes_on_cash_and_cash_equivalents` — Effect of Exchange Rate Changes on Cash and Cash Equivalents  _(group: Net Change in Cash)_
45. `cash_flow_statement_increase_or_decrease_in_cash_cash_equivalents_and_restricted_cash` **[T]** — Increase / (Decrease) in Cash, Cash Equivalents and Restricted Cash  _(group: Net Change in Cash)_  _= +cash_from_operating_activities +cash_from_investing_activities +cash_from_financing_activities +effect_of_exchange_rate_changes_on_cash_and_cash_equivalents_
46. `cash_flow_statement_cash_cash_equivalents_and_restricted_cash_at_beginning_of_period` — Cash, Cash Equivalents and Restricted Cash at Beginning of Period  _(group: Net Change in Cash)_
47. `cash_flow_statement_cash_cash_equivalents_and_restricted_cash_at_end_of_period` **[T]** — Cash, Cash Equivalents and Restricted Cash at End of Period  _(group: Net Change in Cash)_  _= +increase_or_decrease_in_cash_cash_equivalents_and_restricted_cash +cash_cash_equivalents_and_restricted_cash_at_beginning_of_period_
