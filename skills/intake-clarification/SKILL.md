---
name: intake-clarification
description: |
  Decides how to proceed before the full budget/savings/debt analysis pipeline runs:
  ask one combined clarifying question, proceed to analysis, respond to pure
  conversational input (a greeting or thanks with no financial content) without
  running analysis, or block entirely when income is confirmed zero/absent with
  no savings ever stated. Use this skill before analysis_pipeline runs, once per
  intake round (the calling loop caps rounds and stops on its own). Do NOT use
  this skill to perform any actual budget, savings, or debt analysis — it only
  decides whether/how to proceed.
version: 1.1.0
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
- Don't invent a need for clarification when the request is already fully detailed (every category specifically named, surplus destination stated, emergency fund status mentioned) — return `outcome="proceed"`.

## Workflow
1. You receive a JSON object as the user message: `{"original_request": "...", "qna": [{"question": "...", "answer": "..."}, ...]}`. `original_request` is the user's normalized financial data (income/expenses/debts/notes, already extracted by `transaction-fetcher`) or, if nothing financial was said, whatever remains; `qna` is every clarification round already completed this session (empty on the first round).
2. **Round 0 only** (`qna` is empty): if `original_request` shows no income, no expenses, no debts, and nothing in `notes` suggesting real financial content — a pure greeting, thanks, or other pleasantry with nothing to analyze — return `outcome="conversational"` immediately. Don't spend a round asking about vague categories that don't exist; there's nothing here yet to clarify. This check never applies once any real financial content exists anywhere in the conversation (i.e. never on round 1+).
3. **Any round**: if income is *affirmatively confirmed* zero or absent (the input explicitly says "no income," "unemployed," "I don't have a job," etc. — not merely a request that simply doesn't mention income yet) AND no specific savings/investment dollar amount has been stated anywhere in `original_request` or `qna`:
   - If there's a *vague* savings mention with no amount ("I have some savings," "I have money saved") — treat this exactly like any other vague detail: `outcome="ask"`, request the specific amount.
   - If there's no savings mention at all, or a vague one was already asked about and never got an amount, or the user explicitly confirms no savings — return `outcome="blocked"`. Set `rationale` to state plainly that income is confirmed absent and no savings amount was ever given.
   - **Do not** return `outcome="blocked"` just because income hasn't been *mentioned yet* — that's a normal, softer gap `budget-analysis` already handles; only an affirmative confirmation of zero income triggers this.
4. Otherwise, reason — don't string-match — about the three existing gap types:
   - **Vague/unlabeled spending categories**: entries like "$100 others" or "$200 gifting" with no further detail that would materially change budget-analysis's categorization or savings-strategy's cut recommendations.
   - **Unexplained surplus**: if income and expenses are both stated or inferable, do the arithmetic yourself (income − expenses) and check whether the request says what that surplus is already going toward (savings, a goal, nothing yet). An unexplained gap of any real size is worth asking about.
   - **Missing emergency-fund/investment-account info**: the request doesn't say whether the user already has an emergency fund or any existing investment accounts.
5. Skip anything already resolved in `qna` — check each prior question/answer pair before flagging the same gap again.
6. **Re-read `original_request` once more, specifically hunting for an answer to each gap above, stated in plain conversational language rather than a strict field/label.** A sentence like "the surplus goes into my existing brokerage account" answers the surplus-destination question even though there's no field called `surplus_destination`; "I already have a 6-month emergency fund" answers the emergency-fund question even though there's no field called `has_emergency_fund`. Credit these as resolved — don't require the user's original wording to match a category name before counting it.
7. If nothing outstanding survives steps 3–6, return `outcome="proceed"`. When in doubt about whether something genuinely still needs asking after step 6, don't ask — false positives here cost the user a whole round for nothing, which is worse than occasionally proceeding with a minor gap.
8. If something is outstanding (step 3's savings-amount gap, or any of step 4's three gaps), return `outcome="ask"` with **one combined question** covering everything outstanding this round — never multiple separate questions in one turn. Reference your own arithmetic where it helps (e.g. "you have about $1,800/month left over after expenses — what's that currently going toward? Do you already have an emergency fund or any investment accounts?").
9. Populate `target_fields` with short labels for what you're asking about (e.g. `["others_category", "surplus_destination", "emergency_fund"]`) and a one-line `rationale`.

## Examples
- `original_request` is `{"notes": "Thank you so much!"}` (no income, expenses, or debts), `qna=[]` → `outcome="conversational"`.
- `original_request` states income $5000, expenses itemized to the dollar with every category named, surplus destination and emergency-fund status both stated → `outcome="proceed"`.
- `original_request` says `{"notes": "I don't have a job right now."}`, no expenses, no savings mentioned anywhere, `qna=[]` → `outcome="ask"`, asking for expenses and whether there's any savings to work with (not yet blocked — savings status hasn't been asked about yet).
- Same as above, but `qna=[{"question": "...do you have any savings or investments to work with?", "answer": "No, nothing saved."}]` → `outcome="blocked"`, `rationale`: "Income confirmed zero and no savings exist to build a plan around."
- `original_request` says `{"notes": "I'm between jobs but have about $15,000 saved."}` → `outcome="proceed"` (or `outcome="ask"` only if something else, unrelated, is still outstanding) — a specific savings amount was given, so the block doesn't apply; `savings-strategy`/`debt-reduction` will work with the savings figure instead of income.
- `original_request` mentions "$100 others" and "$200 gifting" with no detail, `qna=[]` → `outcome="ask"`, question batches both: "Could you break down what's in your 'others' ($100) and 'gifting' ($200) categories? Also, do you already have an emergency fund or any investment accounts?"

## Output format
Structured `IntakeAssessment`:
- `outcome` — `"ask"` | `"proceed"` | `"conversational"` | `"blocked"`
- `question` — one combined question, set only when `outcome == "ask"`
- `target_fields[]` — short labels for what's being clarified, set only when `outcome == "ask"`
- `rationale` — one line explaining the outcome

## Anti-patterns to avoid
- Don't ask more than one question per round — batch everything outstanding into a single combined question.
- Don't re-ask something already answered in `qna`.
- Don't manage or mention the round cap — that's the calling loop's job, not yours.
- Don't perform or hint at budget/savings/debt analysis — descriptive assessment only.
- Don't flag a request as needing clarification just because it's short — judge by whether the gap would actually change downstream analysis.
- Don't return `outcome="blocked"` just because income wasn't mentioned — only an affirmatively confirmed zero income qualifies, and only once no savings amount exists either.
- Don't return `outcome="conversational"` on round 1+ (once `qna` is non-empty) — by then the conversation has already engaged with real content, even if incomplete.
- Don't accept a vague "I have some savings" as enough to avoid `outcome="blocked"` — ask for the amount first (`outcome="ask"`), same as any other vague detail.
