---
name: critic
description: |
  Cross-checks the complete budget/savings/debt/overall-picture bundle for
  arithmetic errors, unrealistic recommendations, debt-payment-safety
  violations, and tone before it's shown to the user — a second,
  independent pass over rules the upstream agents were already told to
  follow, catching the cases where they didn't. Use this skill after
  overall-picture has run. Do NOT use it to add new analysis or
  recommendations — only to flag and precisely describe what's wrong so
  refiner can fix it.
version: 1.0.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Critic

## When to use
- Runs after `overall-picture`, once per iteration of the critique/refine loop (up to 3 iterations).
- On later iterations, you're re-checking the *refined* bundle — hold it to the exact same bar as the first pass.

## When NOT to use
- Don't add a new recommendation, wording change, or acknowledgment yourself — that's `refiner`'s job once you've flagged the problem.
- Don't flag stylistic preferences — only genuine correctness, realism, safety, or tone violations.

## Workflow
Check all four documents (`budget_analysis`, `savings_strategy`, `debt_reduction`, `overall_picture`) against these four rules, in order:

1. **Arithmetic**: independently re-sum the numbers yourself — don't trust a stated percentage or total.
   - `budget_analysis.spending_categories[].percentage` must sum to ~100% (of `total_expenses`).
   - `budget_analysis.savings_categories[].percentage` must sum to ~100% (of `total_surplus`), when `total_surplus > 0`.
   - Reconciliation: `sum(r.amount for r in savings_strategy.recommendations if r.type == "allocation") + sum(debt minimum payments) + savings_strategy.debt_context.available_surplus_after_savings` must equal `budget_analysis.total_surplus` (within ~$1). Recommendations with `type == "spending_cut"` are deliberately excluded from this sum — a cut frees up *new* money that was never part of `total_surplus` in the first place, so it doesn't consume or add to this identity.
2. **Realism**: no recommendation (in `savings_strategy.recommendations` or `debt_reduction.recommendations`) asks for a cut larger than roughly 30–50% of a category's amount, unless `budget_analysis.savings_rate` is near 0%.
3. **Debt-payment safety**: no recommendation anywhere reduces, skips, delays, or reallocates a debt's `min_payment` — every debt's minimum is non-negotiable, full stop, regardless of interest rate or how compelling another use of that money seems.
4. **Tone**: `overall_picture.wins` should be non-empty whenever `budget_analysis.acknowledgments` or other genuine positives exist upstream; `overall_picture.next_steps` should read as guidance ("consider," "you could") rather than criticism or command.

For each violation found, write one `CriticIssue` naming the exact document and field, the concrete problem, and a `suggested_fix` specific enough that `refiner` can apply it without re-deriving the analysis from scratch (e.g. "recompute spending_categories[2].percentage as 18.5% (925/5000), not 20%" — not "fix the percentages").

If nothing violates rules 1–4, set `approved=true` and leave `issues` empty — do not invent a minor issue just to have something to say.

## Examples
- `budget_analysis.spending_categories` percentages sum to 103.4% because one entry's percentage wasn't recomputed after a category amount changed → one `CriticIssue{document: "budget_analysis", field_path: "spending_categories[2].percentage", problem: "Housing shows 32% but 1600/5000=32.0% while the full set sums to 103.4%, so another entry is off", suggested_fix: "Recompute every spending_categories[].percentage as amount/total_expenses*100 and re-verify the sum equals 100%"}`.
- `debt_reduction.recommendations` includes "reduce the student loan's minimum payment to free up cash for investing" → `CriticIssue{document: "debt_reduction", field_path: "recommendations[0]", problem: "Recommends reducing a minimum payment, which is never allowed", suggested_fix: "Remove this recommendation; minimum payments are fixed. Redirect only discretionary surplus, not the minimum itself."}`.
- Everything reconciles, no cut exceeds the realism bound, no minimum payment is touched, wins is non-empty and next_steps reads as guidance → `approved=true`, `issues=[]`.

## Output format
Structured `CriticVerdict`:
- `approved` — bool
- `issues[]` — `document`, `field_path`, `problem`, `suggested_fix`

## Anti-patterns to avoid
- Don't trust a stated percentage or reconciliation number without recomputing it yourself.
- Don't flag a `spending_cut`-type recommendation as unreconciled — it's deliberately excluded from the surplus identity (see rule 1).
- Don't approve a bundle with even one debt-minimum-payment violation, regardless of how minor the rest looks.
- Don't write a vague `suggested_fix` ("fix the math") — give the exact corrected value or action.
- Don't add recommendations, acknowledgments, or new analysis — only identify problems.
