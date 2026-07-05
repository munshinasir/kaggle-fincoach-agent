---
name: debt-reduction
description: |
  Builds avalanche and snowball debt payoff plans from a list of debts plus the prior
  budget analysis and savings strategy's debt_context, and decides how any leftover
  surplus splits between accelerated debt payoff and investing. Use this skill when
  state['budget_analysis'] and state['savings_strategy'] are populated and the user has
  provided one or more debts. Do NOT use if no debts were provided. Investing suggestions
  here are vehicle/category-level only (e.g. "a low-cost index fund") — never a specific
  stock, fund, or asset pick.
version: 1.1.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Debt Reduction

## When to use
- Final analysis step of the pipeline — runs after `budget-analysis` and `savings-strategy`.
- User has provided at least one debt (name, amount, interest rate, minimum payment).

## When NOT to use
- No debts provided — report `total_debt=0` rather than fabricating a debt.
- Naming a specific stock, fund, or asset to buy — "invest in a low-cost index fund" is in scope; "buy VOO" or "buy Apple stock" is not.

## Workflow
1. Read `state['budget_analysis']` and `state['savings_strategy']` first — respect the cash flow constraints and emergency fund/savings goals already established. Read `savings_strategy.debt_context` specifically: `debt_to_income_ratio`, `available_surplus_after_savings`, `has_emergency_fund`.
2. Analyze each debt by interest rate, balance, and minimum payment.
3. Compute both payoff plans: avalanche (highest interest first) and snowball (smallest balance first) — total interest paid, months to payoff, recommended monthly payment for each. **Minimum/regular payments on every debt are non-negotiable** — they continue regardless of which plan or priority is chosen; only ever reallocate the discretionary surplus, never a debt's own minimum payment. Say explicitly in `recommendations` that regular payments continue on the debts not currently prioritized — don't let the prioritized debt look like the only one still being paid.
4. **Invest-vs-payoff split**: using `available_surplus_after_savings` and each debt's `interest_rate`, decide how to allocate it. For any debt at or below an **investment threshold rate of 6%**, do not recommend directing extra principal to it — a rate that low (e.g. a 0.99% car loan) costs less than typical investment returns, so extra cash is better used elsewhere. Direct extra surplus to the highest-APR debt *above* the threshold first (avalanche-style); once no remaining debt exceeds the threshold, recommend directing the leftover surplus toward investing (vehicle/category only, e.g. "a low-cost index fund" — never a specific pick). Weigh `debt_to_income_ratio` and `has_emergency_fund` too: a high DTI or a missing emergency fund should push the allocation toward debt/safety over investing, even for above-threshold debt.
5. **Realism check** (also enforced later by the Critic, but get it right the first time): a recommendation must never ask for a cut larger than roughly 30-50% of a category unless the user is saving close to nothing overall, and must never suggest reducing or skipping a minimum/regular payment on any debt — not even to pay off a higher-interest one faster.
6. Note the psychological tradeoff (quick wins vs. mathematical optimization) and credit score impact where relevant.
7. Store the result in `state['debt_reduction']`.

## Examples
- Input: `debts=[{name:"Car Loan", amount:22000, interest_rate:0.99, min_payment:400}, {name:"Student Loan", amount:30000, interest_rate:5.99, min_payment:100}]`, `debt_context.available_surplus_after_savings=1550` → the 0.99% car loan gets its $400 minimum only, no extra; the 5.99% student loan (above the 6% threshold? no — see note) — walk the actual numbers rather than assuming a fixed split, but the car loan never receives extra principal ahead of investing or the higher-rate loan.
- Input: `debts=[{name:"Credit Card", amount:4000, interest_rate:22, min_payment:100}]` → Output: avalanche/snowball plans, each with `total_interest` and `months_to_payoff`, plus a recommendation noting the minimum-payment floor.

## Output format
Structured `DebtReduction`:
- `total_debt`, `debts[]`
- `payoff_plans` — `avalanche`, `snowball` (each: `total_interest`, `months_to_payoff`, `monthly_payment`)
- `recommendations[]` — `title`, `description`, `impact` — includes the invest-vs-payoff decision and an explicit note that other debts' regular payments continue

## Anti-patterns to avoid
- Don't recommend a monthly payment that exceeds what the budget analysis shows as available cash flow.
- Don't recommend a specific stock, fund, or other asset — vehicle/category-level investing suggestions only.
- Don't fabricate a debt that wasn't in the input.
- Don't recommend extra principal toward a debt at or below the investment threshold rate while a higher-rate debt or investing opportunity is available.
- Don't ever suggest reducing or skipping a minimum/regular payment on any debt, for any reason — that's an absolute floor, not a tradeoff to weigh.
- Don't ask for a spending cut beyond ~30-50% of a category unless the user's overall savings rate is near zero.
