---
name: refiner
description: |
  Applies critic's specific, itemized fixes to the budget/savings/debt/
  overall-picture bundle — and nothing else. Use this skill only when
  critic_verdict.approved is false and issues are present. Do NOT use it
  to re-derive the analysis from scratch, restyle unflagged content, or
  second-guess a fix critic didn't ask for.
version: 1.0.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Refiner

## When to use
- Runs immediately after `critic`, only when `critic_verdict.approved == false`.

## When NOT to use
- `critic_verdict.approved == true` — there's nothing to refine (the loop should have already stopped before you'd run).
- Don't use this skill to add new recommendations, wording, or analysis beyond what a `CriticIssue` specifically calls for.

## Workflow
1. Read `critic_verdict.issues` — each one names a `document`, `field_path`, `problem`, and `suggested_fix`.
2. Start from the four current documents (`budget_analysis`, `savings_strategy`, `debt_reduction`, `overall_picture`) exactly as given.
3. For each issue, apply its `suggested_fix` precisely to the named `document`/`field_path`. If a fix in one document has a knock-on effect on another (e.g. a corrected `budget_analysis.total_surplus` changes `savings_strategy.debt_context.available_surplus_after_savings`), propagate that specific consequence too — but don't go looking for unrelated things to change.
4. **Every field not touched by an issue must be copied through completely unchanged** — same values, same wording, same order. Do not rephrase, re-summarize, re-derive, or "improve" anything the critic didn't flag. This is a targeted patch, not a rewrite.
5. Output all four documents as one `RefinedBundle`, even though most fields in most calls are just copied forward untouched.

## Examples
- One issue: `{document: "budget_analysis", field_path: "spending_categories[2].percentage", suggested_fix: "Recompute every spending_categories[].percentage as amount/total_expenses*100"}` → recompute every entry's `percentage` in `budget_analysis.spending_categories` (since the fix says "every entry," not just index 2), leave `spending_analysis`, `acknowledgments`, and every other document byte-for-byte identical.
- One issue: `{document: "debt_reduction", field_path: "recommendations[0]", suggested_fix: "Remove this recommendation; minimum payments are fixed."}` → remove only `recommendations[0]` from `debt_reduction.recommendations`, leave `payoff_plans`, `debts`, and everything else in all four documents unchanged. If `overall_picture.next_steps` merged that same removed recommendation in, drop the corresponding `next_steps` entry too (the knock-on effect) — but leave every other `next_steps` entry as-is.

## Output format
Structured `RefinedBundle`: `budget_analysis`, `savings_strategy`, `debt_reduction`, `overall_picture` — same shapes as those agents' own outputs, mostly copied forward.

## Anti-patterns to avoid
- Don't touch a field no `CriticIssue` named, even if you personally would have worded it differently.
- Don't re-derive numbers from scratch — apply the specific `suggested_fix` given.
- Don't drop or invent an issue — apply every one in `critic_verdict.issues`, in full.
- Don't leave a knock-on inconsistency uncorrected (e.g. fixing `total_surplus` but leaving a now-stale `available_surplus_after_savings`) — but don't invent unrelated "improvements" either.
