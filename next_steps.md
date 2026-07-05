# Next Steps

## Resume here (session paused 2026-07-05)

- **Git**: working tree clean, latest commit `18076cb` ("Raise debt-reduction's investment
  threshold rate from 6% to 8%"). Full history: `b73f2ae` (v1 checkpoint) → `076c2af` (v2 Phase 1)
  → `18076cb` (threshold tweak). No remote configured yet (local-only, by design — push to GitHub
  whenever you want, the full history goes up in one shot).
- **Task tracker** (harness TaskList — for reference, may not survive to next session): #7 Step 0
  git checkpoint (done), #8 Phase 1 (done), #9 Phase 2 (pending, not started), #10 Phase 3
  (pending, not started).
- **Original full plan** (background/rationale, already executed through Phase 1): 
  `/home/nasir/.claude/plans/floofy-shimmying-hellman.md` — this file may not persist indefinitely,
  so Phase 2/3 design detail is duplicated below rather than only referenced.
- **Next action**: start Phase 2 (Workflow/@node migration + Intake/Clarification loop) — see full
  design below. Nothing is mid-edit; the codebase is in a clean, working, eval-passing state to
  branch from.
- **No servers/processes left running** — frontend and any `agents-cli playground`/`run` sessions
  were stopped before pausing.

---

## What's built and working (v1 + v2 Phase 1)

5-agent `SequentialAgent` pipeline in `app/agent.py`:
`TransactionFetcherAgent → BudgetAnalysisAgent → SavingsStrategyAgent → DebtReductionAgent → OverallPictureAgent`.
Each analysis agent's instruction lives in `skills/<name>/SKILL.md` (single source of truth, loaded
at runtime via `_load_skill_instruction()`). Local FastAPI frontend at `frontend/main.py`
(`uv run uvicorn frontend.main:app --port 8080`) does one-shot request/response — no session
persistence across requests yet (that's part of Phase 2). Eval suite in `tests/eval/` — 4 metrics,
all passing (`custom_response_quality`, `budget_categories_valid`, `savings_debt_boundary_valid`,
`savings_reconciliation_valid`). Full ownership-chain rule (repeat this before touching any skill):
**`budget-analysis` only describes, never prescribes; `savings-strategy` prescribes spending/savings
actions but only *analyzes* debt (via `debt_context`); `debt-reduction` owns every debt and
invest-vs-payoff prescription; `overall-picture` merges, never adds new analysis.**

## Resolved decisions

- **Architecture foundation**: migrating to ADK's `Workflow`/`@node` graph API (not staying on
  `SequentialAgent`, which is `@deprecated` in the installed `google-adk==2.3.0`). Verified against
  actual installed source, not docs — see plan file for the verification detail if needed.
- **Delivery**: phased (Phase 1 done, Phase 2 next, Phase 3 after).
- **Investing vs. debt payoff threshold**: sequential threshold, not proportional split, currently
  **8%** (raised from an initial 6%, which never triggered any investing against the worked
  example). Revisit only if real usage shows 8% still never triggers investing.

## Eval backlog (not blocking, revisit during Phase 2/3)

- **Cut-vs-allocation reconciliation nuance**: `savings_reconciliation_valid` checks
  `sum(recommendations[].amount) + debt minimums + available_surplus_after_savings == total_surplus`.
  Holds for the current formal eval case (no spending cuts triggered there). Does **not** yet
  correctly handle a case where `recommendations` includes a spending-cut entry — a cut is additive
  to the allocatable pool, not consumptive from it, and `SavingsRecommendation` doesn't distinguish
  cut-type from allocation-type. Confirmed by hand against the worked example, which does trigger
  cuts. Fix with either a `type: "spending_cut" | "allocation"` field or a smarter metric — decide
  during Phase 3, since the Critic needs the same reconciliation logic anyway.
- **Surplus / `savings_categories` case**: not yet eval-covered — (1) `savings_categories` sums to
  100% of `total_surplus`, (2) no surplus/spare-change entry ever appears in `spending_categories`,
  (3) a deficit scenario (expenses ≥ income) produces an empty `savings_categories`, not negative.

---

## Phase 2 — Intake/Clarification loop (Workflow/@node migration)

**Verified ADK facts** (installed `google-adk==2.3.0`, checked against source directly): `BaseAgent`
already `is` a `BaseNode`, so the existing, already-tested `SequentialAgent` (rename to
`analysis_pipeline`, holding all 5 current sub-agents unchanged... actually holding
`budget_analysis_agent → savings_strategy_agent → debt_reduction_agent → overall_picture_agent` —
`transaction_fetcher_agent` moves out, see shape below) drops into a `Workflow` edge **unchanged**.
`output_schema` and tool-calling (including the built-in `request_input` tool) can coexist on one
`Agent` in this version. Resuming requires the client to send a `types.Content` whose part is a
`function_response` with `id == interrupt_id`; a resume message cannot mix a function-response part
with plain text. `Runner` reads `resumability_config` off the `App`, so it must be constructed with
`Runner(app=app, ...)`, not `Runner(agent=root_agent, ...)`.

**Target shape**:
```python
root_agent = Workflow(
    name="FinanceCoachWorkflow",
    edges=[
        (START, transaction_fetcher_agent),
        (transaction_fetcher_agent, intake_loop),
        (intake_loop, analysis_pipeline),
    ],
)
app = App(root_agent=root_agent, name="app",
          resumability_config=ResumabilityConfig(is_resumable=True))
```

**New `IntakeAgent`** (`Agent`, `output_schema=IntakeAssessment`) + new
`skills/intake-clarification/SKILL.md`. Invoked *programmatically* from inside `intake_loop` via
`ctx.run_node(intake_agent, node_input=...)` — not a static Workflow edge, since it must run
conditionally/repeatedly. Given the original request + raw transaction/manual-entry data + prior
Q&A, it reasons (no string matching) about: vague/unlabeled categories (e.g. "$100 others", "$200
gifting" with no detail), unexplained surplus with no stated destination, and missing
emergency-fund/investment-account info — batching everything outstanding into one combined question
per round. It does its own lightweight arithmetic (it already sees income/expenses) to phrase a
surplus-aware question (e.g. "you have ~$1800/month spare — what's that going toward? do you have
an emergency fund?") without waiting for the formal `BudgetAnalysisAgent` run — this reconciles
req. 4's "after budget analysis" phrasing with req. 11's "one stage" (a single pre-analysis intake
stage that's smart enough to reference the numbers without literally running budget-analysis first).
**Open call, not yet made**: confirm this reconciliation is actually what's wanted, vs. two separate
touchpoints (pre- and post-budget-analysis) — flag if it should be revisited.

**Loop mechanics** (`intake_loop`, `@node(rerun_on_resume=True)`, idempotent across reruns): capture
the original request into state once; on each resume, read the answer via `ctx.resume_inputs`,
append to `state['intake_qna']`; stop when the user's answer sets `skip_remaining=True`, a fresh
`IntakeAgent` call returns `needs_clarification=False`, or a **round cap of 2** is hit — whichever
comes first; then write `state['enriched_intake']` and fall through to `analysis_pipeline`. New
schemas needed: `IntakeAssessment{needs_clarification, question, target_fields, rationale}`,
`IntakeAnswer{answer, skip_remaining}`, `IntakeQnA{question, answer}`,
`EnrichedIntake{original_request, qna, proceeded_without_full_info}`. Handoff to the existing
analysis agents uses the established `{state_var}` instruction-interpolation convention (e.g.
`budget_analysis_agent.instruction += "...Intake clarifications: {enriched_intake}"`) — no schema
change needed on `BudgetAnalysis` etc. to consume it.

**`SavingsStrategy.EmergencyFund` schema addition**: add
`existing_investment_accounts: list[ExistingAccount]` where
`ExistingAccount{account_type: str, amount: float}` (types/amounts only, never specific
holdings/picks, per req. 4). Fixes the current bug where emergency-fund sizing always assumes
starting from zero.

**Frontend (`frontend/main.py`) changes**: currently one-shot, no session persistence across HTTP
requests. `Runner(agent=root_agent, ...)` → `Runner(app=app, ...)` (import `app`, not `root_agent`,
from `app.agent`). Persist `session_id` across requests (cookie or hidden form field) instead of a
fresh `uuid4()` per POST. Detect a paused interrupt vs. a normal completion in the event stream; on
interrupt, render the question and a form that submits a `function_response` `Content` (id =
interrupt_id) as the resume message — never mix plain text with a function response on a resume turn.

**Phase 2 verification plan**: manual walkthrough of the worked example end-to-end through the
actual frontend (vague categories + unexplained surplus + no emergency-fund mention → expect 1-2
clarifying rounds → final analysis incorporates the answers), a "proceed anyway" path test, and a
cap-hit test (answer vaguely twice, confirm it proceeds regardless on the 2nd round).

**Files to touch**: `app/agent.py` (Workflow/@node restructure, new schemas, `intake_agent`/
`intake_loop`), new `skills/intake-clarification/SKILL.md`, `frontend/main.py` (session persistence,
resume flow), `AGENTS.md`/`.agents-cli-spec.md` (update the architecture diagram — it currently
still shows the pre-Phase-2 `SequentialAgent`-only shape).

---

## Phase 3 — Critic + Refine loop

Wraps `OverallPictureAgent`'s output in `LoopAgent(sub_agents=[CriticAgent, RefinerAgent],
max_iterations=3)`, escalating once the critic passes. Positioned after Phase 2 so its realism
checks run against real elicited data, not Phase 1's placeholder assumptions.

**`CriticAgent`** checks, concretely: (a) category percentages still sum to 100% across
budget/savings math (and the reconciliation-with-cuts logic from the Eval backlog above — build it
here if not already fixed); (b) no single-category cut recommendation exceeds roughly 30-50%
reduction *unless* `savings_rate` is near 0% (assumption, confirm/adjust); (c) no recommendation
reduces or skips a minimum/regular payment on any debt; (d) tone is affirming — `wins` is non-empty
when the input supports it, next-step framing reads as guidance, not criticism.

**`RefinerAgent`** revises exactly what the critic flagged, informed by its specific complaints —
narrow fix, not a full re-generation.

**Phase 3 verification plan**: at least one eval case that deliberately constructs an input likely
to trigger an unrealistic first-pass recommendation (e.g. near-zero surplus, forcing an
aggressive-cut temptation) and asserts the loop catches and moderates it; confirm no regression on
the Phase 1/2 eval cases.

**Files to touch**: `app/agent.py` (`CriticAgent`, `RefinerAgent`, `LoopAgent`), new
`skills/critic/SKILL.md`.

---

## After Phase 3

- `threat_model.md` (STRIDE-style, per `.agents-cli-spec.md` → Constraints & Safety Rules).
- `agents-cli scaffold enhance . --deployment-target agent_runtime`, then `agents-cli deploy`.
