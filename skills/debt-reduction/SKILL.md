---
name: debt-reduction
description: |
  Builds avalanche and snowball debt payoff plans from a list of debts plus the prior
  budget analysis and savings strategy. Use this skill when state['budget_analysis'] and
  state['savings_strategy'] are populated and the user has provided one or more debts.
  Do NOT use for investment advice, and do NOT use if no debts were provided.
version: 1.0.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Debt Reduction

## When to use
- Final step of the pipeline — runs after `budget-analysis` and `savings-strategy`.
- User has provided at least one debt (name, amount, interest rate, minimum payment).

## When NOT to use
- No debts provided — report `total_debt=0` rather than fabricating a debt.
- Investment or buy-sell recommendations.

## Workflow
1. Read `state['budget_analysis']` and `state['savings_strategy']` first — respect the cash flow constraints and emergency fund/savings goals already established.
2. Analyze each debt by interest rate, balance, and minimum payment.
3. Compute both payoff plans: avalanche (highest interest first) and snowball (smallest balance first) — total interest paid, months to payoff, recommended monthly payment for each.
4. Note the psychological tradeoff (quick wins vs. mathematical optimization) and credit score impact where relevant.
5. Store the result in `state['debt_reduction']`.

## Examples
- Input: `debts=[{name:"Credit Card", amount:4000, interest_rate:22, min_payment:100}]` → Output: avalanche/snowball plans, each with `total_interest` and `months_to_payoff`.

## Output format
Structured `DebtReduction`:
- `total_debt`, `debts[]`
- `payoff_plans` — `avalanche`, `snowball` (each: `total_interest`, `months_to_payoff`, `monthly_payment`)
- `recommendations[]` — `title`, `description`, `impact`

## Anti-patterns to avoid
- Don't recommend a monthly payment that exceeds what the budget analysis shows as available cash flow.
- Don't substitute buy/sell investment advice for debt payoff guidance.
- Don't fabricate a debt that wasn't in the input.
