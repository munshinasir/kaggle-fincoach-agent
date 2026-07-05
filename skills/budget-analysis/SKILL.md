---
name: budget-analysis
description: |
  Analyzes income, transactions, and expenses to categorize spending and describe
  notable spending patterns. Use this skill when the user has provided monthly income
  plus expense or transaction data and wants a spending breakdown. Do NOT use for
  investment advice, debt payoff planning, or prescriptive savings/spending-reduction
  recommendations.
version: 1.2.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Budget Analysis

## When to use
- User has provided income + expenses (manual entry or fetched transactions) and wants a budget breakdown.
- First analysis step of the financial coach pipeline — its output feeds `savings-strategy` and `debt-reduction`.

## When NOT to use
- Investment or buy-sell recommendations (out of scope for the whole agent).
- Debt payoff planning — see `debt-reduction`.
- Prescriptive recommendations of any kind ("reduce X", "cut Y by half", "redirect Z toward savings") — this skill **analyzes**, it does not advise. All action recommendations belong to `savings-strategy`, which reads this skill's output.

## Workflow
1. Analyze income, transactions, and expenses in detail.
2. Categorize spending using only the categories present in the `expenses` (or fetched transaction) data. Every expense in the input must end up in exactly one category — do not add, split, merge, or drop categories. Do not add a category for debt minimum payments or anything from `debts` — debt is handled separately by the debt-reduction skill and must never appear in `spending_categories`. Compute `total_expenses` by re-summing the category amounts yourself — don't reuse an earlier estimate — then double-check: adding the listed category amounts must equal `total_expenses` exactly before you compute any percentage. Each category's `percentage` is `amount ÷ total_expenses × 100`; the percentages across all categories must sum to 100% — if your computed percentages don't sum to ~100%, `total_expenses` is wrong; recompute it before finishing.
3. Compute `total_surplus = monthly_income − total_expenses` (only when `monthly_income` is provided). Do not assume the user has spent their entire income — surplus/spare money is common and must never be folded into `spending_categories` (it is not an expense).
   - If `total_surplus > 0`: categorize it into `savings_categories`, the exact same way `spending_categories` categorizes expenses — each entry has `category`, `amount`, `percentage`, and percentages sum to 100% **of `total_surplus`** (not of income or total_expenses). If the input gives no specific breakdown of how the surplus should be allocated, default to a single category named `"Spare Change"` covering the full `total_surplus` (`percentage: 100`). If the input does specify sub-allocations (e.g. "put $500 toward a vacation fund"), use those named categories instead, still summing to 100% of `total_surplus`.
   - If `total_surplus <= 0` (expenses meet or exceed income) or `monthly_income` is not provided: leave `savings_categories` empty and `total_surplus` at 0 or null — do not report a negative category. A shortfall is itself a descriptive fact, so note it in `spending_analysis` (e.g. "expenses exceed income by $X") — still phrased as an observation, not an instruction.
4. Compute `savings_rate = total_surplus / monthly_income` (as a fraction, e.g. `0.36`) whenever both are known; otherwise leave it null.
5. Populate `acknowledgments` with genuine positive callouts — e.g. `savings_rate >= 0.20`, a category well under its typical ratio, an existing surplus at all. These are warm and specific (cite the number), but still not prescriptive — congratulating isn't advice. If nothing stands out as a win, it's fine for `acknowledgments` to be empty; never invent one.
6. For 3-5 categories worth highlighting, write a purely descriptive `analysis` entry: compare the category's amount to typical spending ratios for the income level (housing ~30%, food ~15%, etc.), to the user's overall income share, and to its share of total spending. State facts and comparisons only.
   - Do NOT include an action verb ("reduce", "cut", "switch", "redirect", "increase") or a dollar savings/outcome estimate anywhere in `analysis` — that is entirely the `savings-strategy` skill's job. If you catch yourself writing "you should..." or "consider...", stop and rephrase as an observation.
   - Example of what NOT to write: "Reduce discretionary spending on dining by half to increase savings." Example of the correct scope: "Your dining budget is high relative to both income and total spend."
   - `spending_analysis` stays neutral/comparative even for categories that are already fine — positive framing belongs in `acknowledgments`, not mixed into `analysis`.
7. Store the result in `state['budget_analysis']` for the next skills in the pipeline to read — `savings-strategy` will read your `spending_analysis` and turn the noteworthy observations into its own recommendations.

## Examples
- Input: `monthly_income=5000`, `dependants=2`, `expenses={Housing:1500, "Eating Out":500, Food:500, ...}` (totaling 3200) → Output: `spending_categories` summing to 100% of 3200, `total_surplus=1800`, `savings_categories=[{category:"Spare Change", amount:1800, percentage:100}]`, and `spending_analysis` including something like:
  ```json
  {"category": "Eating Out", "analysis": "Your current food/dining budget ($1,000 total) is high — 20% of your total income and 31% of your monthly spend — with half dedicated to eating out."}
  ```
  Note there is no "reduce this" instruction and no dollar-savings figure in that entry — that's for `savings-strategy` to derive.

## Output format
Structured `BudgetAnalysis`:
- `total_expenses`, `monthly_income`, `total_surplus`, `savings_rate`
- `spending_categories[]` — `category`, `amount`, `percentage` (sums to 100% of `total_expenses`)
- `savings_categories[]` — `category`, `amount`, `percentage` (sums to 100% of `total_surplus`; empty list if no surplus)
- `spending_analysis[]` — `category`, `analysis` (descriptive text only — no action verbs, no dollar outcome estimates)
- `acknowledgments[]` — genuine positive callouts, specific and warm, never prescriptive; empty list if there's nothing to celebrate

## Anti-patterns to avoid
- Don't leave any input expense uncategorized.
- Don't invent a spending category that isn't present in the input — this includes adding a "debt payment" or "minimum payment" category from `debts`; debt belongs exclusively to the debt-reduction skill.
- Don't put surplus/spare money into `spending_categories` — it always goes in `savings_categories`, even if that means creating the default `"Spare Change"` entry.
- Don't report a negative `savings_categories` amount or percentage — a deficit is an observation, not a category.
- Don't write a `spending_analysis` entry that tells the user what to do, or that estimates a dollar savings/outcome — both are `savings-strategy`'s job, not this skill's. This skill's name is Budget *Analysis*; stay descriptive.
- Don't let `spending_categories` percentages sum to anything other than 100% of `total_expenses`, or `savings_categories` percentages sum to anything other than 100% of `total_surplus` — recompute if a category was added or removed.
- Don't invent an acknowledgment that isn't backed by the numbers — an empty `acknowledgments` list is fine, a fabricated one is not.
- Don't fold positive framing into `spending_analysis` — a category that's genuinely fine belongs in `acknowledgments`, not a softened `analysis` entry.
