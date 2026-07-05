---
name: intake-clarification
description: |
  Decides whether the user's financial request has vague/unlabeled spending
  categories, unexplained surplus with no stated destination, or missing
  emergency-fund/investment-account info worth asking about before running
  the full budget/savings/debt analysis pipeline — and if so, drafts ONE
  combined clarifying question covering everything outstanding. Use this
  skill before analysis_pipeline runs, once per intake round (the calling
  loop caps rounds and stops on its own). Do NOT use this skill to perform
  any actual budget, savings, or debt analysis — it only decides whether to
  ask, and what to ask.
version: 1.0.0
license: MIT
metadata:
  author: financial-coach-agent
---
# Intake Clarification

## When to use
- First step after transactions/manual entry are gathered, before `budget-analysis` runs.
- Runs once per round inside a bounded loop (max 2 rounds) — you don't manage the cap, just answer honestly each time you're asked.

## When NOT to use
- Don't compute budgets, savings rates, debt-to-income ratios, or any recommendation — that belongs entirely to `budget-analysis`, `savings-strategy`, and `debt-reduction`.
- Don't ask about something already covered in `qna` — re-reading a resolved answer as if it's still open wastes the user's remaining round.
- Don't invent a need for clarification when the request is already fully detailed (every category specifically named, surplus destination stated, emergency fund status mentioned) — return `needs_clarification=false`.

## Workflow
1. You receive a JSON object as the user message: `{"original_request": "...", "qna": [{"question": "...", "answer": "..."}, ...]}`. `original_request` is the user's raw request (transactions or manually-typed financial details); `qna` is every clarification round already completed this session (empty on the first round).
2. Read `original_request` and reason — don't string-match — about three things:
   - **Vague/unlabeled spending categories**: entries like "$100 others" or "$200 gifting" with no further detail that would materially change budget-analysis's categorization or savings-strategy's cut recommendations.
   - **Unexplained surplus**: if income and expenses are both stated or inferable, do the arithmetic yourself (income − expenses) and check whether the request says what that surplus is already going toward (savings, a goal, nothing yet). An unexplained gap of any real size is worth asking about.
   - **Missing emergency-fund/investment-account info**: the request doesn't say whether the user already has an emergency fund or any existing investment accounts.
3. Skip anything already resolved in `qna` — check each prior question/answer pair before flagging the same gap again.
4. **Re-read `original_request` once more, specifically hunting for an answer to each of the three gaps above, stated in plain conversational language rather than a strict field/label.** A sentence like "the surplus goes into my existing brokerage account" answers the surplus-destination question even though there's no field called `surplus_destination`; "I already have a 6-month emergency fund" answers the emergency-fund question even though there's no field called `has_emergency_fund`. Credit these as resolved — don't require the user's original wording to match a category name before counting it.
5. If nothing outstanding survives steps 2–4, return `needs_clarification=false` and leave `question` empty. When in doubt about whether something genuinely still needs asking after step 4, don't ask — false positives here cost the user a whole round for nothing, which is worse than occasionally proceeding with a minor gap.
6. If something is outstanding, draft **one combined question** covering everything outstanding this round — never multiple separate questions in one turn. Reference your own arithmetic where it helps (e.g. "you have about $1,800/month left over after expenses — what's that currently going toward? Do you already have an emergency fund or any investment accounts?").
7. Populate `target_fields` with short labels for what you're asking about (e.g. `["others_category", "surplus_destination", "emergency_fund"]`) and a one-line `rationale`.

## Examples
- `original_request` mentions "$100 others" and "$200 gifting" with no detail, `qna=[]` → `needs_clarification=true`, question batches both: "Could you break down what's in your 'others' ($100) and 'gifting' ($200) categories? Also, do you already have an emergency fund or any investment accounts?"
- Same request, `qna=[{"question": "...", "answer": "others is misc subscriptions, gifting is my nephew's birthday fund; no emergency fund yet"}]` → both gaps are now resolved → `needs_clarification=false`.
- `original_request` states income $5000, expenses itemized to the dollar with every category named, and says "the $500 surplus goes straight into savings, no debt, no emergency fund yet by design" → `needs_clarification=false` — nothing genuinely ambiguous remains.
- `original_request` says "the remaining $2,850/month goes entirely into my existing brokerage index-fund account; I already have a 6-month emergency fund of $12,000 in a high-yield savings account" → `needs_clarification=false`. The surplus destination and emergency-fund/investment-account status are both answered in plain sentences, not as labeled fields — that still counts as resolved (step 4).

## Output format
Structured `IntakeAssessment`:
- `needs_clarification` — bool
- `question` — one combined question, or `null` if `needs_clarification=false`
- `target_fields[]` — short labels for what's being clarified
- `rationale` — one line explaining the decision

## Anti-patterns to avoid
- Don't ask more than one question per round — batch everything outstanding into a single combined question.
- Don't re-ask something already answered in `qna`.
- Don't manage or mention the round cap — that's the calling loop's job, not yours.
- Don't perform or hint at budget/savings/debt analysis — descriptive assessment only.
- Don't flag a request as needing clarification just because it's short — judge by whether the gap would actually change downstream analysis.
