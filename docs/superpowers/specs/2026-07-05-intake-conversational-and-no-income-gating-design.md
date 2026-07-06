# Intake Conversational/No-Action Gating — Design

## Context

Every frontend submission starts a brand-new session (`frontend/main.py`'s `/api/analyze` always
calls `session_service.create_session` with a fresh `uuid4()`), and the backend `Workflow` assumes
every session's first message contains — or will, after clarification, contain — real financial
data to analyze. Two real bugs follow from that assumption:

1. **Pure chit-chat triggers the full pipeline.** If a user's message after a completed analysis
   (or any first message) is a greeting or pleasantry ("Thank you!", "Hi there"), `TransactionFetcherAgent`
   extracts essentially nothing, `IntakeAgent` asks a clarifying question anyway, and if the user's
   reply is also non-financial (or the 2-round cap is hit), `analysis_pipeline` runs regardless —
   producing a nonsensical "financial picture" built on $0 income.
2. **No hard gate for "we cannot help."** Even with genuine engagement, if a user confirms they have
   no income and no savings, nothing stops `analysis_pipeline` from still running savings/debt/
   recommendation logic against zero data, producing hollow or misleading prescriptive output.

This design adds two new terminal outcomes to the existing intake step, reusing `IntakeAgent`'s
already-established role (deciding whether to proceed to analysis) rather than adding a new agent.

## Decisions Already Locked

- **Savings exemption**: any *specific stated dollar amount* of savings/investments (cash, emergency
  fund, brokerage, retirement — any amount, no minimum size, no runway-vs-expenses calculation) is
  enough to avoid the no-action block, treated as the resource to plan around instead of income. A
  *vague* mention ("I have some savings") with no amount is a normal clarification gap — `IntakeAgent`
  asks for the amount, same as any other vague detail — not an immediate pass or block.
- **Block content**: when the no-action block fires, the response is *purely* the block message —
  no partial spending breakdown, no numbers, nothing that could read as a partial plan.
- **Round-cap behavior for unconfirmed income**: hitting the 2-round intake cap with income simply
  *never stated* (not affirmatively confirmed as zero) does **not** trigger the block — that falls
  through to `budget-analysis`'s existing soft handling of unknown income (nulls, no fabrication).
  Only an *affirmatively confirmed* zero income triggers the hard block.

## Schema Change

`IntakeAssessment` (`app/agent.py`) replaces `needs_clarification: bool` with a discriminated:

```python
outcome: Literal["ask", "proceed", "conversational", "blocked"]
```

`question`, `target_fields`, `rationale` are unchanged, meaningful only when `outcome == "ask"`. This
is a targeted refactor of the existing boolean (not an additive bolt-on) specifically to prevent
invalid states — e.g. a bolted-on `intent`/`no_income_no_savings` pair could otherwise disagree with
`needs_clarification` in ways that don't correspond to any real decision.

## `skills/intake-clarification/SKILL.md` — New Decisions

Checked in this order, before the existing three gap-checks (vague categories, unexplained surplus,
missing emergency-fund info):

1. **Round 0 only** (`qna` is empty): if the normalized input (income/expenses/debts/notes) shows no
   financial content at all — pure greeting, thanks, or chit-chat — return `outcome="conversational"`
   immediately, skipping straight past clarification. This check only ever fires on the very first
   assessment of a session; once any real financial content exists anywhere in the conversation, it
   never fires again for that session.
2. **Any round**: if income is *affirmatively confirmed* zero/absent ("no income," "unemployed" — not
   merely unmentioned) AND no savings/investment dollar amount has been stated anywhere in the input
   or `qna`:
   - A vague savings mention with no amount → `outcome="ask"`, request the amount (a normal
     clarification gap, per the locked decision above).
   - No savings mention at all, or a vague one went unanswered through the round cap, or the user
     explicitly confirms no savings → `outcome="blocked"`.
3. Otherwise, existing behavior: `outcome="ask"` for any of the three original gap types, or
   `outcome="proceed"` when nothing is outstanding.

## Workflow Changes (`app/agent.py`)

**New terminal nodes**, matching `halted_node`'s existing plain-function pattern — no LLM call, fixed
text, for the same reason `security_checkpoint`'s messages are fixed: tone and wording must never
drift on messages this consequential.

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
    return _CONVERSATIONAL_NUDGE

def no_action_node(node_input: str) -> str:
    return _NO_INCOME_NO_SAVINGS_BLOCK
```

`intake_loop` yields `route="analysis"` (today's default, when `outcome=="proceed"` or the round cap
is hit with `skip_remaining`/unconfirmed income), `route="conversational"` (when `outcome=="conversational"`),
or `route="blocked"` (when `outcome=="blocked"`) — instead of always falling through unconditionally
to `analysis_pipeline`.

**Interaction with `skip_remaining`**: today, checking "skip remaining questions" short-circuits
straight to `route="analysis"` without calling `IntakeAgent` again. That would let a user who already
affirmatively confirmed no income and no savings (in an earlier round) skip past the block simply by
declining to answer a *later*, unrelated question. Fix: `skip_remaining` now triggers one final
`IntakeAgent` assessment call (with the accumulated `qna`, including the just-given answer) instead
of bypassing it. If that assessment returns `outcome="blocked"`, honor it — a confirmed
no-income-no-savings conclusion can't be skipped past. Any other outcome (`"ask"` or `"proceed"`) is
treated as `route="analysis"`, matching the user's actual intent to stop being asked questions.

**Workflow edges**, extending the existing conditional-routing pattern already used by
`security_checkpoint`:

```python
(intake_loop, {"analysis": analysis_pipeline, "conversational": conversational_node, "blocked": no_action_node}),
```

Both new terminal nodes bypass `critique_refine_loop` entirely — a fixed-text message has no numeric
content to fact-check, so critiquing it would add cost and latency for nothing.

## Frontend Changes

**`frontend/main.py`**: generalize the existing `_find_halted_message` (added for the security-halt
fix) into `_find_terminal_message`, keyed by `event.node_info.name`:

```python
_TERMINAL_NODE_RESPONSE_TYPES = {
    "halted_node": "halted",
    "conversational_node": "conversational",
    "no_action_node": "blocked",
}
```

returning `{"type": <mapped type>, "session_id", "message"}` — the same mechanism already in place,
now covering three node names instead of one.

**`frontend/static/app.js`**: `"halted"` and `"conversational"` both render as plain assistant prose
using the existing terminal-message renderer (broadened, not duplicated) — both are calm,
session-ending messages with no further action available. `"blocked"` gets a new, visually distinct
treatment: a bordered card with a short heading ("We can't help with this yet") and the message
below, in a warm/neutral color — never red/alarming, consistent with this app's calm-tone rule —
giving it the visual weight the block deserves without breaking tone.

## Testing

- **Unit (pytest)**: extend the existing terminal-message test (fake `event.node_info.name` objects)
  to cover all three node names, not just `halted_node`.
- **Smoke (real Gemini calls)**:
  - A fresh session's first message is a pure greeting/thanks → `"conversational"`, message exactly
    matches `_CONVERSATIONAL_NUDGE`.
  - A session that establishes confirmed-zero income and confirmed-no-savings → `"blocked"`, message
    exactly matches `_NO_INCOME_NO_SAVINGS_BLOCK`.
  - Confirmed-zero income *with* a stated savings amount (e.g. "$15,000 saved") → proceeds to
    `"final"` normally, proving the exemption works.
  - Existing golden-path smoke test still reaches `"final"` unchanged (regression check — confirms
    normal financial input never accidentally routes to either new terminal).

## Scope Boundaries

- No changes to `budget-analysis`, `savings-strategy`, `debt-reduction`, `overall-picture`, `critic`,
  or `refiner` — the decision is fully resolved before `analysis_pipeline` ever runs, so nothing
  downstream needs to know either new case exists.
- No changes to the intake round cap (`MAX_INTAKE_ROUNDS = 2`) or to `security_checkpoint`.
- No session-continuity changes — a `"conversational"` or `"blocked"` response ends that session
  exactly like `"halted"`/`"final"` do today; the next message starts a fresh session, unchanged from
  the existing one-shot-per-message frontend architecture.
