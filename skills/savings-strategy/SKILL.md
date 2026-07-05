---
name: savings-strategy
description: |
  Creates a personalized savings plan — emergency fund sizing, savings allocations, AND
  the prescriptive spending-reduction recommendations that budget-analysis deliberately
  leaves out — from a completed budget analysis. Use this skill when state['budget_analysis']
  is already populated and the user wants savings or emergency-fund guidance. Do NOT use
  before a budget analysis exists, and do NOT use for debt payoff planning.
version: 1.1.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Savings Strategy

## When to use
- Second step of the pipeline — runs only after `budget-analysis` has populated `state['budget_analysis']`.

## When NOT to use
- No budget analysis available yet — do not guess at spending categories.
- Debt-specific payoff planning — see `debt-reduction`.

## Workflow
1. Read `state['budget_analysis']` first — including `spending_categories`, `spending_analysis` (budget-analysis's descriptive observations, e.g. "dining is 31% of spend"), and `total_surplus`/`savings_categories`. Do not re-derive spending categories.
2. This skill owns all prescriptive action: for each notable observation in `spending_analysis`, independently decide the concrete action (e.g. "reduce by half"), and estimate the monthly amount it would free up. Don't just restate budget-analysis's wording — form your own judgment from the underlying figures (amount, income share, spend share) and add what budget-analysis intentionally omitted: the verb and the number.
3. Recommend a savings allocation across purposes (emergency fund, retirement, specific goals, and/or directing freed-up cash toward debt), considering risk factors (job stability, dependants), `total_surplus`/`savings_categories` if present, and progressive savings rates as discretionary income increases.
4. **Merge and deduplicate before finalizing `recommendations`**: compare your step-2 spending-reduction drafts against your step-3 allocation drafts. If two entries target the same category or make substantially the same point (e.g. a "cut dining" entry and a separate "redirect savings from dining" entry), combine them into ONE entry with unified reasoning — never emit two recommendations about the same category. The final list must read as one coherent set of decisions, not two lists stapled together.
5. Calculate emergency fund size from total expenses and dependants (default: `total_expenses × 6` months; adjust upward for more dependants or job instability, and state whatever multiplier was used).
6. Suggest practical automation techniques (e.g. automatic transfer on payday).
7. Store the result in `state['savings_strategy']` for `debt-reduction` to read.

## Examples
- Input: `state['budget_analysis']` with `total_expenses=3200`, `spending_analysis=[{category:"Eating Out", analysis:"$1,000 total (dining is half), 20% of income, 31% of spend"}]` → this skill produces `recommendations` including something like `{category:"Eating Out", amount:250, rationale:"Cut dining out by half — it's 31% of your spend and matches your grocery bill — freeing $250/mo toward debt payoff"}`. Note the action verb and dollar figure that budget-analysis's `spending_analysis` entry did not include.
- Input: `state['budget_analysis']` with `total_expenses=3000` → Output also includes `emergency_fund.recommended_amount=18000` (6× multiplier, stated), plus automation techniques.

## Output format
Structured `SavingsStrategy`:
- `emergency_fund` — `recommended_amount`, `current_amount`, `current_status`
- `recommendations[]` — `category`, `amount`, `rationale` — a single, deduplicated list combining spending-reduction actions and savings allocations
- `automation_techniques[]` — `name`, `description`

## Anti-patterns to avoid
- Don't recommend a savings amount that ignores essential expenses identified in the budget analysis.
- Don't omit the multiplier/rationale used for the emergency fund size — it must be traceable.
- Don't copy a `spending_analysis` entry's text into a recommendation unchanged — add the concrete action and dollar amount.
- Don't emit two separate `recommendations` entries for the same category (e.g. one framed as a spending cut, another as a savings allocation) — merge into one.
