---
name: savings-strategy
description: |
  Creates a personalized savings plan — emergency fund sizing, savings allocations, AND
  the prescriptive spending-reduction recommendations that budget-analysis deliberately
  leaves out — from a completed budget analysis, adapted to the user's actual savings
  intent rather than a one-size-fits-all "cut spending" default. Also analyzes (but does
  not prescribe) the user's debt picture for debt-reduction to act on. Use this skill when
  state['budget_analysis'] is already populated and the user wants savings or
  emergency-fund guidance. Do NOT use before a budget analysis exists, and do NOT use for
  debt payoff planning or naming dollar amounts to direct at specific debts.
version: 1.3.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Savings Strategy

## When to use
- Second step of the pipeline — runs only after `budget-analysis` has populated `state['budget_analysis']`.

## When NOT to use
- No budget analysis available yet — do not guess at spending categories.
- Debt-specific payoff planning, or naming a dollar amount to direct at a specific debt — see `debt-reduction`. This skill analyzes debt's relationship to savings; it does not decide how to pay debt off.

## Workflow
1. Read `state['budget_analysis']` first — including `spending_categories`, `spending_analysis`, `total_surplus`/`savings_categories`, `savings_rate`, and `acknowledgments`. Do not re-derive spending categories.
2. **Reserve debt minimum payments before allocating anything.** `total_surplus` is `income − expenses` and does not account for debts (budget-analysis never sees them). If the user has any debts, compute `discretionary_surplus = total_surplus − sum(each debt's minimum/regular payment)` and treat *that* — not raw `total_surplus` — as your allocatable pool for every recommendation below. If there are no debts, `discretionary_surplus = total_surplus`. Skipping this step is the most common way this skill's numbers stop adding up: a debt's minimum payment is money that's already spoken for.
3. **Open with the acknowledgments, restated warmly** — don't just copy budget-analysis's wording verbatim; build on it in your own words before any recommendation. If `acknowledgments` is empty, skip this rather than inventing praise.
4. **Intent branching**: if `savings_rate >= 0.20`, do not recommend spending cuts — this user is already saving well. The exception is when there's no emergency fund: cuts to accelerate building one are still fair game even at a high savings rate. Emergency-fund status usually isn't stated in the input (nothing has asked the user yet) — when it's genuinely unknown, say so explicitly ("I don't have information on an existing emergency fund, so I'm assuming one still needs to be built — let me know if you already have one") rather than silently assuming zero. Only fall back to step 5's spending-reduction path when `savings_rate < 0.20`, or when there's no emergency fund regardless of rate.
5. When cuts are warranted (per step 4): for each notable observation in `spending_analysis`, independently decide the concrete action (e.g. "reduce by half") and estimate the monthly amount it would free up. Don't just restate budget-analysis's wording — form your own judgment from the underlying figures (amount, income share, spend share) and add what budget-analysis intentionally omitted: the verb and the number. Keep cuts realistic — see debt-reduction's realism note, the same bar applies here. Mark each of these `type: "spending_cut"` — this frees up *new* money from an existing expense that isn't part of `total_surplus`/`discretionary_surplus` yet (the cut is a proposal, not something already reflected in the numbers), so it's excluded from step 11's reconciliation check.
6. Recommend a savings allocation across purposes (emergency fund, retirement, specific goals) **from `discretionary_surplus`**, considering risk factors (job stability, dependants) and progressive savings rates as discretionary income increases. Do **not** name a specific debt or a dollar amount to direct at one, and do not decide an invest-vs-debt-payoff split — that's `debt-reduction`'s call, informed by `debt_context` (step 9). Mark each of these `type: "allocation"` — it spends money already sitting in `discretionary_surplus`, so it counts toward step 11's reconciliation check.
7. **Merge and deduplicate before finalizing `recommendations`**: compare your step-5 spending-reduction drafts against your step-6 allocation drafts. If two entries target the same category or make substantially the same point, combine them into ONE entry with unified reasoning — never emit two recommendations about the same category. The final list must read as one coherent set of decisions, not two lists stapled together.
8. Calculate emergency fund size from total expenses and dependants (default: `total_expenses × 6` months; adjust upward for more dependants or job instability, and state whatever multiplier was used).
9. Suggest practical automation techniques (e.g. automatic transfer on payday).
10. Build `debt_context` for debt-reduction: `debt_to_income_ratio` (total monthly debt payments ÷ `monthly_income`, if debts and income are both known), `available_surplus_after_savings` (`discretionary_surplus` from step 2 minus what you allocated in steps 5-6 — never raw `total_surplus`), `has_emergency_fund` (your best-known answer from step 4 — `null` if genuinely unknown, never a silent guess), and a short descriptive `note`. `note` states facts only — the surplus amount, the DTI ratio, that debts exist — with **no directive verbs**: don't write "should be applied/directed toward," "prioritize," "aggressively pay down," or "recommend." Merely mentioning that debt exists (e.g. "there is $500/mo surplus and one outstanding debt") is fine even when there's only one debt to refer to; telling debt-reduction (or the user) what to *do* with it is not — that decision, including which debt to focus on and how, is entirely debt-reduction's to make.
11. Store the result in `state['savings_strategy']` for `debt-reduction` to read. **Sanity check before storing**: `sum(r.amount for r in recommendations if r.type == "allocation") + available_surplus_after_savings` must equal `discretionary_surplus` exactly. `spending_cut`-type entries are excluded from this sum — they don't draw from or add to `discretionary_surplus`, since the cut hasn't happened in the numbers yet. If it doesn't reconcile, find the error before finishing.

## Examples
- `savings_rate = 0.36`, no emergency fund mentioned → open with an acknowledgment ("you're saving well above the 20% mark"), then still recommend building an emergency fund (the exception in step 3), not spending cuts.
- `savings_rate = 0.05`, `spending_analysis=[{category:"Eating Out", analysis:"$1,000 total (dining is half), 20% of income, 31% of spend"}]` → `recommendations` includes something like `{category:"Eating Out", amount:250, rationale:"Cut dining out by half — it's 31% of your spend and matches your grocery bill — freeing up $250/mo", type:"spending_cut"}`. Note there is no "toward debt payoff" framing — where the freed cash goes is debt-reduction's decision, not this skill's. This entry is excluded from step 11's reconciliation sum (see step 5).
- Output also includes `emergency_fund.recommended_amount=18000` (6× multiplier, stated) and, after reserving a $100/mo debt minimum from `total_surplus` per step 2, `debt_context={debt_to_income_ratio: 0.18, available_surplus_after_savings: 500, has_emergency_fund: null, note: "..."}`.

## Output format
Structured `SavingsStrategy`:
- `emergency_fund` — `recommended_amount`, `current_amount`, `current_status`
- `recommendations[]` — `category`, `amount`, `rationale`, `type` (`"spending_cut"` or `"allocation"`) — a single, deduplicated list; never names a specific debt or directs an amount at one
- `automation_techniques[]` — `name`, `description`
- `debt_context` — `debt_to_income_ratio`, `available_surplus_after_savings`, `has_emergency_fund`, `note`

## Anti-patterns to avoid
- Don't allocate from raw `total_surplus` without first reserving debt minimum payments (`discretionary_surplus`) — this is the single most common way the numbers stop reconciling.
- Don't recommend a savings amount that ignores essential expenses identified in the budget analysis.
- Don't omit the multiplier/rationale used for the emergency fund size — it must be traceable.
- Don't copy a `spending_analysis` entry's text into a recommendation unchanged — add the concrete action and dollar amount.
- Don't emit two separate `recommendations` entries for the same category — merge into one.
- Don't mislabel a `type` — a cut that frees up new money is `"spending_cut"`, an allocation that spends `discretionary_surplus` is `"allocation"`. Mislabeling breaks the reconciliation check.
- Don't recommend spending cuts when `savings_rate >= 0.20` and an emergency fund is confirmed to exist — acknowledge instead.
- Don't silently assume no emergency fund exists when the input doesn't say — state the assumption explicitly.
- Don't name a specific debt, say which one to prioritize, or direct a dollar amount at one, in `recommendations` — that's `debt-reduction`'s decision.
- Don't use directive verbs in `debt_context.note` ("should," "prioritize," "aggressively pay down," "apply/direct toward," "recommend") — state the surplus and DTI facts and stop. Mentioning that a debt exists is fine; telling debt-reduction what to do about it is not.
- Don't skip opening with acknowledgments when budget-analysis provided real ones.
