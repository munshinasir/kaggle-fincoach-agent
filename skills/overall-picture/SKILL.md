---
name: overall-picture
description: |
  Synthesizes budget analysis, savings strategy, and debt reduction into one consolidated,
  prioritized "Overall Financial Picture" — the final output of the pipeline. Use this
  skill when state['budget_analysis'], state['savings_strategy'], and state['debt_reduction']
  are all populated. Do NOT use before all three are ready, and do NOT introduce any new
  financial analysis or recommendation not already present in those three outputs.
version: 1.0.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Overall Picture

## When to use
- Final step of the pipeline — runs after `budget-analysis`, `savings-strategy`, and `debt-reduction` have all populated their state.

## When NOT to use
- Any of the three prior states is missing.
- Introducing a new recommendation, number, or analysis not traceable to the three upstream outputs — this skill merges and prioritizes, it does not add new financial reasoning.

## Workflow
1. Read `state['budget_analysis']`, `state['savings_strategy']`, and `state['debt_reduction']` in full.
2. Collect `wins`: pull `budget_analysis.acknowledgments` forward. Never fabricate a win that isn't backed by the upstream outputs; an empty list is acceptable, a fabricated one is not.
3. Build one merged, prioritized `next_steps` list combining `savings_strategy.recommendations` and `debt_reduction.recommendations` — do not simply concatenate the two lists. If two recommendations from different upstream agents address the same category or amount of money (e.g. savings-strategy freed up cash and debt-reduction directs where it goes), merge them into a single `NextStep` that tells the full story, not two entries that read as contradictory or redundant.
4. Assign `priority` (1 = highest) based on financial impact and urgency: minimum-payment-adjacent debt actions and emergency-fund gaps typically outrank discretionary optimizations, but defer to what the upstream agents already flagged as time-sensitive rather than re-deriving priority from scratch.
5. Keep the tone affirming throughout — this is the client-facing summary. Lead with wins where they exist, frame `next_steps` as guidance ("here's what would help most"), not criticism.
6. Store the result in `state['overall_picture']`.

## Examples
- `budget_analysis.acknowledgments=["Your savings rate is 36%, well above the 20% benchmark"]`, `savings_strategy.recommendations` includes an emergency-fund allocation, `debt_reduction.recommendations` includes a car-loan-minimum-only + student-loan-priority + index-fund suggestion → `wins=["Your savings rate is 36%, well above the 20% benchmark"]`, `next_steps` merges the emergency-fund and debt/invest actions into one prioritized list, not two separate blocks.

## Output format
Structured `OverallPicture`:
- `wins[]` — positive callouts pulled from `budget_analysis.acknowledgments`
- `next_steps[]` — `category`, `action`, `amount`, `priority` — one merged, prioritized list

## Anti-patterns to avoid
- Don't introduce a number, category, or recommendation not present in the three upstream outputs.
- Don't concatenate `savings_strategy.recommendations` and `debt_reduction.recommendations` without checking for overlap — merge anything addressing the same money or category.
- Don't fabricate a win, and don't omit a real one.
- Don't let the framing read as critical — this is the "guide," not the "critic" (that's a later stage).
