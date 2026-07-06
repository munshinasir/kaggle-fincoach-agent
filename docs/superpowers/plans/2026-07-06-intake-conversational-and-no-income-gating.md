# Intake Conversational/No-Action Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop pure chit-chat ("Thank you!") and confirmed-zero-income-with-no-savings input from
running the full analysis pipeline and producing a bogus $0-income financial picture; instead route
both to fixed, calm terminal responses.

**Architecture:** Extend `IntakeAgent`'s existing screening role (it already sits right before
`analysis_pipeline` and already reasons over the normalized income/expenses/debts/notes) with a
4-way `outcome` decision instead of today's boolean `needs_clarification`. Two new outcomes
(`"conversational"`, `"blocked"`) route `intake_loop` to two new fixed-text terminal nodes, using the
exact same conditional-routing mechanism `security_checkpoint`'s `{"clean": ..., "halted": ...}`
edges already use. The frontend generalizes its existing terminal-message detection (added for the
security-halt fix) to cover the two new node names, and adds one new visual treatment for the block.

**Tech Stack:** No new dependencies. Same stack as the rest of the project (Google ADK `Workflow`/`@node`,
FastAPI JSON API, vanilla JS).

## Global Constraints

- `IntakeAssessment.outcome: Literal["ask", "proceed", "conversational", "blocked"]` replaces the
  existing `needs_clarification: bool` field — a discriminated union, not an additive boolean, to
  avoid invalid state combinations.
- **Savings exemption**: any specific stated dollar amount of savings/investments (any size, no
  runway calculation) exempts a $0-income user from the block. A vague mention with no amount
  ("I have some savings") is a normal clarification gap (`outcome="ask"`, request the amount) — not
  an immediate pass or block.
- **Block content**: when the block fires, the response is *purely* the fixed block message — no
  partial spending breakdown, no numbers.
- **Round-cap with unconfirmed income does not block**: hitting the 2-round cap with income simply
  never stated (not affirmatively confirmed zero) falls through to today's existing behavior
  (`budget-analysis`'s soft handling of unknown income). Only an affirmatively confirmed zero blocks.
- **`"conversational"` only fires on round 0** (`qna` empty) — never once any real financial content
  exists anywhere in the conversation.
- **Terminal message text is fixed** (not LLM-authored), exactly:
  ```
  _CONVERSATIONAL_NUDGE = (
      "Happy to chat! I'm best at building out a full financial picture, though — "
      "share your income, expenses, and any debts (typed or as an uploaded statement) "
      "and I'll put together a budget, savings, and debt-payoff plan for you."
  )
  _NO_INCOME_NO_SAVINGS_BLOCK = (
      "We can't put together a financial plan right now — there's no income or savings "
      "for us to build a strategy around. If that changes (a job, a benefit, or some "
      "savings), come back and we'll take a full look."
  )
  ```
- Both new terminal nodes bypass `critique_refine_loop` entirely.
- **A final blocked-check must run before falling through to "analysis"** whenever `intake_loop` is
  about to stop asking questions with a just-appended answer — this covers both `skip_remaining=True`
  *and* the round-cap being exhausted via a normal (non-skip) answer, so a just-confirmed
  no-income-no-savings conclusion can never be skipped past either way.
- No changes to `budget-analysis`, `savings-strategy`, `debt-reduction`, `overall-picture`, `critic`,
  `refiner`, `security_checkpoint`, or `MAX_INTAKE_ROUNDS` (stays `2`).
- Frontend adds two new API response types, `"conversational"` and `"blocked"`, alongside the
  existing `"question"`/`"security"`/`"halted"`/`"final"`. `"conversational"` reuses the existing
  plain-prose terminal rendering (same as `"halted"`). `"blocked"` gets a new, visually distinct
  "large block" treatment — warm/neutral color, never red/alarming.

---

### Task 1: Backend routing — schema, skill, Workflow edges, terminal nodes

**Files:**
- Modify: `app/agent.py` (imports, `IntakeAssessment` at `app/agent.py:302-313`, `intake_loop` at
  `app/agent.py:529-582`, new terminal nodes after `halted_node` at `app/agent.py:585-587`, Workflow
  edges at `app/agent.py:648-649`)
- Modify: `skills/intake-clarification/SKILL.md` (full rewrite, version 1.0.0 → 1.1.0)
- Modify: `.agents-cli-spec.md` (update the `intake_loop`/`analysis_pipeline` architecture lines)
- Test: `tests/smoke/test_intake_gating_smoke.py` (new)

**Interfaces:**
- Produces (used by Task 2): module-level constants `_CONVERSATIONAL_NUDGE: str`,
  `_NO_INCOME_NO_SAVINGS_BLOCK: str` in `app/agent.py`; two new terminal node functions
  `conversational_node(node_input: str) -> str` and `no_action_node(node_input: str) -> str`,
  registered in the `Workflow`'s edges under route keys `"conversational"` and `"blocked"` — Task 2's
  `frontend/main.py` will detect these by `event.node_info.name == "conversational_node"` /
  `"no_action_node"`, the same technique already used for `"halted_node"`.

- [ ] **Step 1: Add the `Literal` import**

In `app/agent.py`, the import block currently starts:

```python
import re
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
```

Change to:

```python
import re
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Literal
```

- [ ] **Step 2: Replace the `IntakeAssessment` schema**

In `app/agent.py:302-313`, replace:

```python
class IntakeAssessment(BaseModel):
    needs_clarification: bool = Field(
        ..., description="True if the request has vague/unlabeled categories, unexplained surplus, or missing emergency-fund/investment info worth asking about"
    )
    question: str | None = Field(
        None,
        description="One combined question covering everything outstanding this round — never multiple separate questions",
    )
    target_fields: list[str] = Field(
        default_factory=list, description="Which fields/categories this question is trying to clarify"
    )
    rationale: str | None = Field(None, description="Why clarification is (or isn't) needed")
```

with:

```python
class IntakeAssessment(BaseModel):
    outcome: Literal["ask", "proceed", "conversational", "blocked"] = Field(
        ...,
        description=(
            "'ask' — needs one more clarifying question this round. 'proceed' — nothing "
            "outstanding, ready for analysis. 'conversational' — round 0 only, no financial "
            "content at all (pure greeting/thanks). 'blocked' — income is affirmatively "
            "confirmed zero/absent and no savings/investment amount was ever stated."
        ),
    )
    question: str | None = Field(
        None,
        description="One combined question covering everything outstanding this round — only set when outcome == 'ask'",
    )
    target_fields: list[str] = Field(
        default_factory=list, description="Which fields/categories this question is trying to clarify"
    )
    rationale: str | None = Field(None, description="Why this outcome was chosen")
```

- [ ] **Step 3: Replace the `intake_loop` function**

In `app/agent.py:529-582`, replace the entire function:

```python
@node(rerun_on_resume=True)
async def intake_loop(ctx: Context, node_input: str) -> AsyncGenerator[Event, None]:
    """Bounded (max 2 rounds) clarification loop, run before analysis_pipeline.

    Batches everything IntakeAgent flags into one combined question per round.
    Stops early if IntakeAgent finds nothing to ask, or the user sets
    skip_remaining=True. Always ends by writing state['enriched_intake'] —
    analysis_pipeline's SequentialAgent doesn't consume node_input directly,
    so the handoff goes through state, matching the {state_var} convention
    every other agent in this pipeline already uses.
    """
    original_request = node_input
    qna: list[dict] = list(ctx.state.get("intake_qna") or [])
    round_num = len(qna)

    interrupt_id = f"intake_round_{round_num}"
    if interrupt_id in ctx.resume_inputs:
        answer = ctx.resume_inputs[interrupt_id]
        if answer.get("skip_remaining"):
            enriched = EnrichedIntake(
                original_request=original_request,
                qna=[IntakeQnA(**q) for q in qna],
                proceeded_without_full_info=True,
            ).model_dump()
            yield Event(output=enriched, state={"enriched_intake": enriched})
            return
        pending_question = ctx.state.get("intake_pending_question", "")
        qna = qna + [{"question": pending_question, "answer": answer.get("answer", "")}]
        round_num += 1

    if round_num < MAX_INTAKE_ROUNDS:
        assessment = await ctx.run_node(
            intake_agent,
            node_input={"original_request": original_request, "qna": qna},
            run_id=f"assess_{round_num}",
        )
        if assessment.get("needs_clarification"):
            question = assessment.get("question") or (
                "Could you clarify any vague or missing details in your request?"
            )
            yield Event(state={"intake_qna": qna, "intake_pending_question": question})
            yield RequestInput(
                interrupt_id=f"intake_round_{round_num}",
                message=question,
                response_schema=IntakeAnswer,
            )
            return

    enriched = EnrichedIntake(
        original_request=original_request,
        qna=[IntakeQnA(**q) for q in qna],
        proceeded_without_full_info=round_num >= MAX_INTAKE_ROUNDS and bool(qna),
    ).model_dump()
    yield Event(output=enriched, state={"enriched_intake": enriched})
```

with:

```python
@node(rerun_on_resume=True)
async def intake_loop(ctx: Context, node_input: str) -> AsyncGenerator[Event, None]:
    """Bounded (max 2 rounds) clarification loop, run before analysis_pipeline.

    Batches everything IntakeAgent flags into one combined question per round.
    Routes to "analysis" (the default), "conversational" (round 0, no financial
    content at all), or "blocked" (income confirmed zero/absent with no savings
    ever stated) based on IntakeAgent's outcome. Whenever the loop is about to
    stop asking questions with a just-appended answer — either skip_remaining
    was checked, or the round cap was just exhausted by a normal answer — one
    final assessment call checks specifically for "blocked" before falling
    through, so a just-confirmed no-income-no-savings conclusion can never be
    skipped past either way. Always writes state['enriched_intake'] on the
    "analysis" route — analysis_pipeline's SequentialAgent doesn't consume
    node_input directly, so the handoff goes through state, matching the
    {state_var} convention every other agent in this pipeline already uses.
    """
    original_request = node_input
    qna: list[dict] = list(ctx.state.get("intake_qna") or [])
    round_num = len(qna)
    just_answered = False
    force_stop = False

    interrupt_id = f"intake_round_{round_num}"
    if interrupt_id in ctx.resume_inputs:
        answer = ctx.resume_inputs[interrupt_id]
        pending_question = ctx.state.get("intake_pending_question", "")
        qna = qna + [{"question": pending_question, "answer": answer.get("answer", "")}]
        round_num += 1
        just_answered = True
        force_stop = bool(answer.get("skip_remaining"))

    if not force_stop and round_num < MAX_INTAKE_ROUNDS:
        assessment = await ctx.run_node(
            intake_agent,
            node_input={"original_request": original_request, "qna": qna},
            run_id=f"assess_{round_num}",
        )
        outcome = assessment.get("outcome")
        if outcome == "conversational":
            yield Event(route="conversational")
            return
        if outcome == "blocked":
            yield Event(route="blocked")
            return
        if outcome == "ask":
            question = assessment.get("question") or (
                "Could you clarify any vague or missing details in your request?"
            )
            yield Event(state={"intake_qna": qna, "intake_pending_question": question})
            yield RequestInput(
                interrupt_id=f"intake_round_{round_num}",
                message=question,
                response_schema=IntakeAnswer,
            )
            return
        # outcome == "proceed" falls through below
    elif just_answered:
        assessment = await ctx.run_node(
            intake_agent,
            node_input={"original_request": original_request, "qna": qna},
            run_id=f"assess_final_{round_num}",
        )
        if assessment.get("outcome") == "blocked":
            yield Event(route="blocked")
            return

    enriched = EnrichedIntake(
        original_request=original_request,
        qna=[IntakeQnA(**q) for q in qna],
        proceeded_without_full_info=force_stop or (round_num >= MAX_INTAKE_ROUNDS and bool(qna)),
    ).model_dump()
    yield Event(output=enriched, state={"enriched_intake": enriched}, route="analysis")
```

- [ ] **Step 4: Add the two new terminal nodes**

In `app/agent.py`, right after the existing `halted_node` function (`app/agent.py:585-587`):

```python
def halted_node(node_input: str) -> str:
    """Terminal node for the 'halted' route — the run ends here, analysis_pipeline never runs."""
    return node_input
```

add:

```python
_CONVERSATIONAL_NUDGE = (
    "Happy to chat! I'm best at building out a full financial picture, though — "
    "share your income, expenses, and any debts (typed or as an uploaded statement) "
    "and I'll put together a budget, savings, and debt-payoff plan for you."
)

_NO_INCOME_NO_SAVINGS_BLOCK = (
    "We can't put together a financial plan right now — there's no income or savings "
    "for us to build a strategy around. If that changes (a job, a benefit, or some "
    "savings), come back and we'll take a full look."
)


def conversational_node(node_input: str) -> str:
    """Terminal node for the 'conversational' route — round-0 chit-chat with no financial content."""
    return _CONVERSATIONAL_NUDGE


def no_action_node(node_input: str) -> str:
    """Terminal node for the 'blocked' route — confirmed zero income, no savings ever stated."""
    return _NO_INCOME_NO_SAVINGS_BLOCK
```

- [ ] **Step 5: Update the Workflow edges**

In `app/agent.py:648-649`, replace:

```python
        (security_checkpoint, {"clean": intake_loop, "halted": halted_node}),
        (intake_loop, analysis_pipeline),
```

with:

```python
        (security_checkpoint, {"clean": intake_loop, "halted": halted_node}),
        (intake_loop, {"analysis": analysis_pipeline, "conversational": conversational_node, "blocked": no_action_node}),
```

- [ ] **Step 6: Rewrite `skills/intake-clarification/SKILL.md`**

Replace the entire file content with:

```markdown
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
```

- [ ] **Step 7: Update `.agents-cli-spec.md`'s architecture description**

Replace:

```
  - → `intake_loop` (`@node(rerun_on_resume=True)`) — bounded (2-round) clarification loop; calls
    `IntakeAgent` (`Agent`, `output_schema`) via `ctx.run_node()` — skill: `intake-clarification` —
    decides whether to ask, never analyzes. Pauses via `RequestInput`/resumes via a
    `function_response` addressed to the same `interrupt_id` when clarification is needed.
  - → `analysis_pipeline` (`SequentialAgent` — drops into the `Workflow` edge unchanged)
```

with:

```
  - → `intake_loop` (`@node(rerun_on_resume=True)`) — bounded (2-round) clarification loop; calls
    `IntakeAgent` (`Agent`, `output_schema`) via `ctx.run_node()` — skill: `intake-clarification` —
    decides `outcome`: ask, proceed, conversational (round-0 chit-chat with no financial content),
    or blocked (confirmed zero income, no savings ever stated). Pauses via `RequestInput`/resumes via
    a `function_response` addressed to the same `interrupt_id` when asking. Routes to
    `analysis_pipeline` (normal), `conversational_node` (fixed friendly nudge, terminal), or
    `no_action_node` (fixed "can't help" block, terminal) — the latter two are plain functions, no
    LLM call, and bypass `critique_refine_loop` entirely.
  - → `analysis_pipeline` (`SequentialAgent` — drops into the `Workflow` edge unchanged; reached only
    via `intake_loop`'s "analysis" route)
```

- [ ] **Step 8: Write the smoke test**

Create `tests/smoke/test_intake_gating_smoke.py`:

```python
"""Runnable smoke test (NOT pytest) for the new intake-loop routing added to
gate against pure chit-chat and confirmed-zero-income-with-no-savings input,
exercising real Gemini calls end to end via app.agent.app directly (not
through the frontend). See
docs/superpowers/specs/2026-07-05-intake-conversational-and-no-income-gating-design.md.

The existing golden-path smoke tests (test_transaction_fetcher_typed_text_smoke.py,
test_frontend_api_smoke.py) already cover normal financial input reaching
analysis — this file only covers the two new terminal routes plus the savings
exemption that keeps a genuine case from being wrongly blocked.

Run with: uv run python tests/smoke/test_intake_gating_smoke.py
"""

import asyncio
import uuid

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import _CONVERSATIONAL_NUDGE, _NO_INCOME_NO_SAVINGS_BLOCK  # noqa: E402
from app.agent import app as adk_app  # noqa: E402

REQUEST_INPUT = "adk_request_input"
MAX_ROUNDS = 4  # generous bound: MAX_INTAKE_ROUNDS (2) plus slack for resume overhead


def find_pending(events):
    for e in reversed(events):
        if e.content and e.content.parts:
            for p in e.content.parts:
                if p.function_call and p.function_call.name == REQUEST_INPUT:
                    return p.function_call.id
    return None


def find_terminal(events):
    """Returns (node_name, output) for a plain-function terminal node's own
    event.output, if the run ended at one — same technique frontend/main.py
    uses (event.node_info.name, since plain-function @node output surfaces
    via event.output, not event.content).
    """
    for e in events:
        name = getattr(e.node_info, "name", None)
        if name in {"conversational_node", "no_action_node", "halted_node"} and isinstance(
            e.output, str
        ):
            return name, e.output
    return None


async def run_until_terminal_or_final(runner, session_id, first_message):
    """Drives one session through however many intake rounds it takes,
    answering "" with skip_remaining=True on any question, until either a
    terminal node fires or the run has no more pending interrupts (implying
    it reached analysis_pipeline/critique_refine_loop).
    """
    new_message = first_message
    for _ in range(MAX_ROUNDS):
        events = [
            e
            async for e in runner.run_async(
                user_id="tester", session_id=session_id, new_message=new_message
            )
        ]
        terminal = find_terminal(events)
        if terminal is not None:
            return terminal

        interrupt_id = find_pending(events)
        if interrupt_id is None:
            return None  # no more interrupts and no terminal node -> reached analysis

        new_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=interrupt_id,
                        name=REQUEST_INPUT,
                        response={"answer": "", "skip_remaining": True},
                    )
                )
            ],
        )
    raise AssertionError(f"did not reach a terminal or final state within {MAX_ROUNDS} rounds")


async def check_conversational() -> None:
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    message = types.Content(role="user", parts=[types.Part.from_text(text="Thank you so much!")])
    terminal = await run_until_terminal_or_final(runner, session_id, message)
    assert terminal is not None, "expected a terminal node for pure chit-chat input"
    name, output = terminal
    assert name == "conversational_node", f"expected conversational_node, got {name}: {output!r}"
    assert output == _CONVERSATIONAL_NUDGE, f"expected the fixed nudge text, got: {output!r}"
    print("Conversational-nudge smoke assertion passed.")


async def check_blocked() -> None:
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "I don't have a job right now and no savings at all. "
                    "My rent is $1200 a month."
                )
            )
        ],
    )
    terminal = await run_until_terminal_or_final(runner, session_id, message)
    assert terminal is not None, "expected a terminal node for confirmed no-income-no-savings input"
    name, output = terminal
    assert name == "no_action_node", f"expected no_action_node, got {name}: {output!r}"
    assert output == _NO_INCOME_NO_SAVINGS_BLOCK, f"expected the fixed block text, got: {output!r}"
    print("No-income-no-savings block smoke assertion passed.")


async def check_savings_exemption() -> None:
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "I have no income right now, but I have $15,000 saved in a "
                    "high-yield savings account. My rent is $1200 a month."
                )
            )
        ],
    )
    terminal = await run_until_terminal_or_final(runner, session_id, message)
    assert terminal is None, f"expected no terminal node (should proceed to analysis), got: {terminal}"

    session = await session_service.get_session(app_name="app", user_id="tester", session_id=session_id)
    assert session.state.get("overall_picture"), "expected analysis_pipeline to have run and populated overall_picture"
    print("Savings-exemption smoke assertion passed — proceeded to analysis despite zero income.")


async def main() -> None:
    await check_conversational()
    await check_blocked()
    await check_savings_exemption()
    print("\nAll intake-gating smoke assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 9: Run the smoke test**

Run: `uv run python tests/smoke/test_intake_gating_smoke.py`
Expected: `All intake-gating smoke assertions passed.` (all three `check_*` functions print their own success line first).

- [ ] **Step 10: Commit**

```bash
git add app/agent.py skills/intake-clarification/SKILL.md .agents-cli-spec.md tests/smoke/test_intake_gating_smoke.py
git commit -m "Add conversational/blocked intake routing to stop chit-chat and zero-income input from running full analysis"
```

---

### Task 2: `frontend/main.py` — generalize terminal-message detection

**Files:**
- Modify: `frontend/main.py` (`_find_halted_message` at `frontend/main.py:56-69`, its call site in
  `_run_turn` at `frontend/main.py:89-92`)
- Modify: `tests/unit/test_frontend_api.py`
- Modify: `tests/smoke/test_frontend_api_smoke.py`

**Interfaces:**
- Consumes (from Task 1): terminal node names `"conversational_node"`, `"no_action_node"` (alongside
  the existing `"halted_node"`), and the fixed constants `_CONVERSATIONAL_NUDGE`/
  `_NO_INCOME_NO_SAVINGS_BLOCK` for test assertions.
- Produces (used by Task 3): API responses now also return `{"type": "conversational", ...}` and
  `{"type": "blocked", ...}`, in addition to the existing four types.

- [ ] **Step 1: Write the failing unit tests**

In `tests/unit/test_frontend_api.py`, replace the import line:

```python
from frontend.main import _find_halted_message, app
```

with:

```python
from frontend.main import _find_terminal_message, app
```

Replace the two existing `_find_halted_message` tests:

```python
def test_find_halted_message_returns_the_halted_node_output():
    events = [
        SimpleNamespace(node_info=SimpleNamespace(name="security_checkpoint"), output=None),
        SimpleNamespace(
            node_info=SimpleNamespace(name="halted_node"),
            output="Stopped at your request after a security check.",
        ),
    ]
    assert (
        _find_halted_message(events)
        == "Stopped at your request after a security check."
    )


def test_find_halted_message_returns_none_when_no_halted_node_present():
    events = [
        SimpleNamespace(node_info=SimpleNamespace(name="intake_loop"), output=None),
        SimpleNamespace(node_info=SimpleNamespace(name="analysis_pipeline"), output=None),
    ]
    assert _find_halted_message(events) is None
```

with:

```python
def test_find_terminal_message_returns_halted_type():
    events = [
        SimpleNamespace(node_info=SimpleNamespace(name="security_checkpoint"), output=None),
        SimpleNamespace(
            node_info=SimpleNamespace(name="halted_node"),
            output="Stopped at your request after a security check.",
        ),
    ]
    assert _find_terminal_message(events) == (
        "halted",
        "Stopped at your request after a security check.",
    )


def test_find_terminal_message_returns_conversational_type():
    events = [
        SimpleNamespace(
            node_info=SimpleNamespace(name="conversational_node"),
            output="Happy to chat! I'm best at building out a full financial picture, though...",
        ),
    ]
    result = _find_terminal_message(events)
    assert result is not None
    assert result[0] == "conversational"


def test_find_terminal_message_returns_blocked_type():
    events = [
        SimpleNamespace(
            node_info=SimpleNamespace(name="no_action_node"),
            output="We can't put together a financial plan right now...",
        ),
    ]
    result = _find_terminal_message(events)
    assert result is not None
    assert result[0] == "blocked"


def test_find_terminal_message_returns_none_when_no_terminal_node_present():
    events = [
        SimpleNamespace(node_info=SimpleNamespace(name="intake_loop"), output=None),
        SimpleNamespace(node_info=SimpleNamespace(name="analysis_pipeline"), output=None),
    ]
    assert _find_terminal_message(events) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_frontend_api.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name '_find_terminal_message' from 'frontend.main'`.

- [ ] **Step 3: Update `frontend/main.py`**

Replace `_find_halted_message` (`frontend/main.py:56-69`):

```python
def _find_halted_message(events: list) -> str | None:
    """Returns the halt message if the run ended via halted_node's terminal
    route (the user declined to proceed past a security check), else None.

    halted_node writes no session state — its message only exists as this
    plain-function node's own event.output (ADK's convention for
    plain-function @node output, distinct from an LlmAgent's event.content).
    """
    for event in events:
        if getattr(event.node_info, "name", None) == "halted_node" and isinstance(
            event.output, str
        ):
            return event.output
    return None
```

with:

```python
_TERMINAL_NODE_RESPONSE_TYPES = {
    "halted_node": "halted",
    "conversational_node": "conversational",
    "no_action_node": "blocked",
}


def _find_terminal_message(events: list) -> tuple[str, str] | None:
    """Returns (response_type, message) if the run ended at one of the
    plain-function terminal nodes (halted_node, conversational_node,
    no_action_node), else None.

    These nodes write no session state — their message only exists as their
    own event.output (ADK's convention for plain-function @node output,
    distinct from an LlmAgent's event.content).
    """
    for event in events:
        name = getattr(event.node_info, "name", None)
        if name in _TERMINAL_NODE_RESPONSE_TYPES and isinstance(event.output, str):
            return _TERMINAL_NODE_RESPONSE_TYPES[name], event.output
    return None
```

Then in `_run_turn` (`frontend/main.py:89-92`), replace:

```python
    halted_message = _find_halted_message(events)
    if halted_message is not None:
        _pending.pop(session_id, None)
        return {"type": "halted", "session_id": session_id, "message": halted_message}
```

with:

```python
    terminal = _find_terminal_message(events)
    if terminal is not None:
        response_type, message = terminal
        _pending.pop(session_id, None)
        return {"type": response_type, "session_id": session_id, "message": message}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_frontend_api.py -v`
Expected: PASS — all tests green (the 3 pre-existing tests plus the 4 new/renamed terminal-message tests).

- [ ] **Step 5: Add smoke-test scenarios**

In `tests/smoke/test_frontend_api_smoke.py`, add these two constants near the top, after `DIRTY_MESSAGE`:

```python
CONVERSATIONAL_MESSAGE = "Thank you so much for your help!"

NO_INCOME_NO_SAVINGS_MESSAGE = (
    "I don't have a job right now and no savings at all. My rent is $1200 a month."
)
```

Add these two functions after `check_stop_here_returns_halted_response`:

```python
def check_conversational_nudge_via_api(client: TestClient) -> None:
    """Confirms a pure-pleasantry first message gets a "conversational" nudge
    instead of triggering the full analysis pipeline with zero data.
    """
    response = client.post("/api/analyze", data={"message": CONVERSATIONAL_MESSAGE})
    data = response.json()
    assert response.status_code == 200, data
    assert data["type"] == "conversational", f"expected a conversational response, got: {data}"
    assert "financial picture" in data["message"].lower(), data
    print("Conversational-nudge-via-API smoke assertion passed.")


def check_no_income_no_savings_block_via_api(client: TestClient) -> None:
    """Confirms confirmed-zero-income-with-no-savings reaches a "blocked"
    response instead of a bogus zero-income analysis, resuming past any
    intake questions with skip_remaining=True along the way.
    """
    response = client.post("/api/analyze", data={"message": NO_INCOME_NO_SAVINGS_MESSAGE})
    data = response.json()
    assert response.status_code == 200, data

    for _ in range(4):
        if data["type"] == "blocked":
            break
        assert data["type"] in ("question", "security"), f"unexpected response type: {data}"
        session_id = data["session_id"]
        if data["type"] == "security":
            response = client.post(
                "/api/resume-security", json={"session_id": session_id, "proceed": True}
            )
        else:
            response = client.post(
                "/api/resume",
                json={"session_id": session_id, "answer": "", "skip_remaining": True},
            )
        data = response.json()
        assert response.status_code == 200, data

    assert data["type"] == "blocked", f"expected a blocked response, got: {data}"
    assert "can't put together a financial plan" in data["message"].lower(), data
    print("No-income-no-savings-block-via-API smoke assertion passed.")
```

Then in `main()`, after the existing `check_stop_here_returns_halted_response(client)` call, add:

```python
    check_conversational_nudge_via_api(client)
    check_no_income_no_savings_block_via_api(client)
```

- [ ] **Step 6: Run the smoke test**

Run: `uv run python tests/smoke/test_frontend_api_smoke.py`
Expected: all five print lines appear, ending with the new
`No-income-no-savings-block-via-API smoke assertion passed.`

- [ ] **Step 7: Commit**

```bash
git add frontend/main.py tests/unit/test_frontend_api.py tests/smoke/test_frontend_api_smoke.py
git commit -m "Generalize frontend terminal-message detection to cover conversational/blocked routes"
```

---

### Task 3: Frontend rendering — the "large block" and the conversational nudge

**Files:**
- Modify: `frontend/static/app.js` (`handleResponse` at `frontend/static/app.js:167-179`, add
  `renderBlockedTurn` near `renderHaltedTurn` at `frontend/static/app.js:159-165`)
- Modify: `frontend/static/style.css` (add `.no-action-block` rules)

**Interfaces:**
- Consumes (from Task 2): API responses `{"type": "conversational", "message": str}` and
  `{"type": "blocked", "message": str}`.
- Produces: nothing consumed by a later task — this is the final rendering layer.

- [ ] **Step 1: Update `frontend/static/app.js`**

Add a new function right after the existing `renderHaltedTurn` (`frontend/static/app.js:159-165`):

```javascript
  function renderHaltedTurn(message) {
    const turn = addAssistantTurn();
    const p = document.createElement("p");
    p.textContent = message;
    turn.appendChild(p);
    sessionId = null;
  }

  function renderBlockedTurn(message) {
    const turn = addAssistantTurn();
    const block = document.createElement("div");
    block.className = "no-action-block";
    const heading = document.createElement("h3");
    heading.textContent = "We can't help with this yet";
    const p = document.createElement("p");
    p.textContent = message;
    block.appendChild(heading);
    block.appendChild(p);
    turn.appendChild(block);
    sessionId = null;
  }
```

Then replace `handleResponse` (`frontend/static/app.js:167-179`):

```javascript
  function handleResponse(data) {
    if (data.type === "question") {
      renderQuestionTurn(data.message);
    } else if (data.type === "security") {
      renderSecurityTurn(data.message);
    } else if (data.type === "halted") {
      renderHaltedTurn(data.message);
    } else if (data.type === "final") {
      renderFinalTurn(data.confirmation_html, data.recommendations_html);
    } else {
      renderQuestionTurn(data.message || "Something went wrong — please try again.");
    }
  }
```

with:

```javascript
  function handleResponse(data) {
    if (data.type === "question") {
      renderQuestionTurn(data.message);
    } else if (data.type === "security") {
      renderSecurityTurn(data.message);
    } else if (data.type === "halted" || data.type === "conversational") {
      renderHaltedTurn(data.message);
    } else if (data.type === "blocked") {
      renderBlockedTurn(data.message);
    } else if (data.type === "final") {
      renderFinalTurn(data.confirmation_html, data.recommendations_html);
    } else {
      renderQuestionTurn(data.message || "Something went wrong — please try again.");
    }
  }
```

- [ ] **Step 2: Add the CSS**

In `frontend/static/style.css`, after the `.button.primary` rule at the end of the file:

```css
.button.primary {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}
```

add:

```css
.no-action-block {
  background: #fdf6ec;
  border: 1px solid #e8d5b0;
  border-radius: 1rem;
  padding: 20px 24px;
  margin: 8px 0;
}

.no-action-block h3 {
  margin: 0 0 8px;
  font-size: 1.1rem;
}

.no-action-block p {
  margin: 0;
  color: var(--text);
}
```

- [ ] **Step 3: Structural verification via curl**

Start the dev server: `uv run uvicorn frontend.main:app --port 8080`

```bash
curl -s http://127.0.0.1:8080/static/app.js | grep -c "renderBlockedTurn\|no-action-block"
curl -s http://127.0.0.1:8080/static/style.css | grep -c "no-action-block"
```

Expected: both commands print a nonzero count, confirming the new function/class names are present
in the served files (not just the source tree).

Stop the server: `Ctrl+C` (or `pkill -f "uvicorn frontend.main:app"` if backgrounded).

- [ ] **Step 4: Commit**

```bash
git add frontend/static/app.js frontend/static/style.css
git commit -m "Add large-block rendering for the no-action response and reuse plain rendering for conversational nudges"
```

---

### Task 4: Full-suite verification and manual browser QA

**Files:** none created or modified — verification only.

**Interfaces:** none.

- [ ] **Step 1: Run the full automated test suite**

Run: `uv run pytest tests/unit/ -v`
Expected: PASS — every test green, including all of Task 1-3's new/updated tests and every
pre-existing test (`test_security_checkpoint.py`, `test_presenter.py`, `test_dummy.py`, etc.).

- [ ] **Step 2: Run every smoke test touched by or adjacent to this change**

```bash
uv run python tests/smoke/test_intake_gating_smoke.py
uv run python tests/smoke/test_frontend_api_smoke.py
uv run python tests/smoke/test_transaction_fetcher_typed_text_smoke.py
uv run python tests/smoke/test_security_escalation_smoke.py
```

Expected: PASS for all four. Note: `test_security_escalation_smoke.py` has previously shown one
LLM-non-determinism-sensitive assertion (typed-text PII-preservation wording) that failed once and
passed on immediate re-run, unrelated to this branch's changes (that test's own upstream code,
`security_checkpoint`, is untouched by this plan) — if it fails, re-run it once before treating it as
a real regression.

- [ ] **Step 3: Manual browser verification**

Start the dev server:

```bash
uv run uvicorn frontend.main:app --port 8080
```

In a browser at `http://127.0.0.1:8080/`, verify:
1. Type "Thank you so much!" as the very first message — confirm you get a plain, friendly nudge
   response (no clarifying question, no financial picture), and the input box is free to accept a
   new message afterward.
2. Type "I don't have a job right now and no savings at all. My rent is $1200 a month." — answer any
   clarifying question(s) that appear — confirm you eventually see a visually distinct block (bordered
   card, warm color, heading "We can't help with this yet") with no numbers or spending breakdown.
3. Type "I have no income right now, but I have $15,000 saved. My rent is $1200 a month." — confirm
   this reaches a normal full financial picture (not blocked), proving the savings exemption works
   visually, not just via the API.
4. Re-run the existing golden path (a complete income/expenses/debt message) — confirm it still
   reaches a normal final analysis, unaffected by this change.

- [ ] **Step 4: Stop the dev server**

Press `Ctrl+C` in the terminal running `uvicorn`.

- [ ] **Step 5: Final commit (only if Step 3 surfaced fixes)**

If manual verification required any code changes, commit them now with a message describing what was
fixed. If no changes were needed, skip this step — Tasks 1-3's commits already cover the complete
implementation.
