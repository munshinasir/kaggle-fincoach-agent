# Next Steps

## Resume here (session paused after Phase 2, 2026-07-05)

- **Git**: Phase 2 changes complete and smoke-tested, about to be committed. History so far:
  `b73f2ae` (v1 checkpoint) → `076c2af` (v2 Phase 1) → `18076cb` (threshold tweak) → Phase 2 commit
  (this session). No remote configured yet (local-only, by design).
- **Task tracker**: #7 Step 0 git checkpoint (done), #8 Phase 1 (done), #9 Phase 2 (done), #10
  Phase 3 (pending, not started — this is the next action).
- **Next action**: start Phase 3 (Critic + Refine loop) — see design below. Nothing is mid-edit;
  the codebase is in a clean, working state to branch from.
- **No servers/processes left running** — frontend and any ad hoc smoke-test scripts were stopped
  before pausing.

---

## What's built and working (v1 + v2 Phase 1 + v2 Phase 2)

`app/agent.py` is now a `Workflow` (`FinanceCoachWorkflow`, `resumability_config=ResumabilityConfig(is_resumable=True)`):
`START → TransactionFetcherAgent → intake_loop → analysis_pipeline` where `analysis_pipeline` is
the same `SequentialAgent` as before (`BudgetAnalysisAgent → SavingsStrategyAgent →
DebtReductionAgent → OverallPictureAgent`), now used as a `Workflow` node. `intake_loop` is a
bounded (2-round) clarification loop that runs before analysis — see the Phase 2 section below for
what it does and how it was verified. Each analysis agent's instruction lives in
`skills/<name>/SKILL.md` (single source of truth, loaded at runtime via `_load_skill_instruction()`).
Local FastAPI frontend at `frontend/main.py` (`uv run uvicorn frontend.main:app --port 8080`) now
persists `session_id` per browser session and handles the intake loop's pause/resume via a
`function_response` form post — see Phase 2 section for the exact wire format. Full ownership-chain
rule (repeat this before touching any skill): **`budget-analysis` only describes, never prescribes;
`savings-strategy` prescribes spending/savings actions but only *analyzes* debt (via
`debt_context`); `debt-reduction` owns every debt and invest-vs-payoff prescription;
`overall-picture` merges, never adds new analysis.** `intake-clarification` only decides whether to
ask a clarifying question — never analyzes.

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
- **`agents-cli eval generate` can't run a `Workflow`-typed root agent** (new, found during Phase 2):
  `client.evals.run_inference` (the Vertex eval SDK `agents-cli` calls into) crashes with
  `AttributeError: 'str' object has no attribute 'get'` in `_inference_runner.py`'s
  `_extract_new_events_from_partial` — `agent_data` comes back as a raw string instead of a nested
  dict for a `Workflow` root agent, regardless of whether the run pauses on an intake interrupt (a
  fully-detailed prompt that never triggers the intake loop still crashes identically). The
  `_patch_eval_tool_introspection` docstring in that same vendored file suggests the Vertex eval SDK
  was written against `SequentialAgent`-style workflow agents before ADK's `Workflow` graph class
  existed — this looks like a genuine upstream gap, not a bug in this project's code. **Do not patch
  `agents-cli`'s vendored script.** Worked around for Phase 2 by running the agent directly via
  `Runner(app=app, ...)` and feeding the captured session events into `tests/eval/*_metric.py`'s
  `evaluate()` by hand (see the Phase 2 section below for the exact pattern) — this reproduced all
  three deterministic Phase 1 checks passing against the new architecture. Revisit
  `agents-cli eval generate` after a `google-agents-cli`/`google-adk` version bump; `basic-dataset.json`'s
  prompt was also reworded (same categories/amounts, added detail) so it no longer trips the intake
  loop, in case `eval generate` starts working again before the underlying gap is fixed.

---

## Phase 2 — Intake/Clarification loop (Workflow/@node migration) — DONE

**Verified ADK facts** (installed `google-adk==2.3.0`, checked against source directly, not just
docs — see `AGENTS.md` for the source files): a plain `BaseAgent` (e.g. `SequentialAgent`)
auto-wraps as an `AgentNode` when placed in a `Workflow` edge, so `analysis_pipeline` (the renamed
`SequentialAgent`, `transaction_fetcher_agent` removed from its `sub_agents`) dropped in unchanged.
`ctx.run_node(agent, node_input=some_dict)` JSON-serializes `some_dict` and injects it as a
user-role turn before a single-turn `LlmAgent` node runs (confirmed in
`workflow/_llm_agent_wrapper.py::_node_input_to_content`) — so `IntakeAgent` genuinely receives
`{"original_request": ..., "qna": [...]}` as its input, no `{state_var}` plumbing needed for that
call. The HITL wire format (confirmed in `workflow/utils/_workflow_hitl_utils.py` and
`_rehydration_utils.py`): a node-level `yield RequestInput(interrupt_id=..., message=...,
response_schema=IntakeAnswer)` produces the exact same `adk_request_input` function-call event as
the tool-based `request_input` mechanism; the client resumes with a `types.Content(role="user",
parts=[types.Part(function_response=types.FunctionResponse(id=interrupt_id,
name="adk_request_input", response={...}))])`, and the response dict is validated against
`response_schema` before landing in `ctx.resume_inputs[interrupt_id]` as a plain dict.
**Important**: `_to_event()` does NOT merge a node's pending `ctx.state` mutations into a bare
`yield RequestInput(...)` — state must be yielded as its own `Event(state={...})` *before* the
`RequestInput` yield, in the same generator pass, or it's silently lost across the pause. `Runner`
reads `resumability_config` off the `App`, so it must be constructed with `Runner(app=app, ...)`,
not `Runner(agent=root_agent, ...)`.

**Shape actually built** (`app/agent.py`):
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

**`IntakeAgent`** (`Agent`, `output_schema=IntakeAssessment`) + `skills/intake-clarification/SKILL.md`,
invoked from inside `intake_loop` via `ctx.run_node(intake_agent, node_input={"original_request":
..., "qna": [...]}, run_id=f"assess_{round_num}")`. Reasons (no string matching) about
vague/unlabeled categories, unexplained surplus with no stated destination, and missing
emergency-fund/investment-account info, batching everything outstanding into one combined question
per round. **Reconciliation decision made**: it does its own lightweight arithmetic against
`original_request` rather than waiting for a formal `BudgetAnalysisAgent` run — one combined
pre-analysis intake stage, not two separate touchpoints. This wasn't revisited with the user since
Phase 2 shipped end-to-end working via smoke testing; flag it if it turns out to feel wrong in
practice.

**Loop mechanics** (`intake_loop`, `@node(rerun_on_resume=True)`, reruns fully from scratch on every
resume — `round_num = len(qna)` from `ctx.state['intake_qna']` recomputes cleanly each time): stops
when a fresh `IntakeAgent` call returns `needs_clarification=False`, the user's answer sets
`skip_remaining=True`, or **`MAX_INTAKE_ROUNDS=2`** is hit — whichever comes first; then always
writes `state['enriched_intake']` (both on the fully-resolved path and the skip/cap paths) before
falling through to `analysis_pipeline`. Schemas: `IntakeAssessment{needs_clarification, question,
target_fields, rationale}`, `IntakeAnswer{answer, skip_remaining}`, `IntakeQnA{question, answer}`,
`EnrichedIntake{original_request, qna, proceeded_without_full_info}`. Handoff to
`BudgetAnalysisAgent` goes through `state['enriched_intake']` + `{enriched_intake}` instruction
interpolation (the established `{state_var}` convention) — `analysis_pipeline`'s `SequentialAgent`
doesn't consume a Workflow node's `node_input` directly, so state is the only reliable handoff path.

**Real bug found and fixed during smoke testing** (not a design gap, a genuine defect):
`TransactionFetcherAgent`'s passthrough JSON had no field for free-text context — "the surplus goes
into my brokerage account" / "I already have a 6-month emergency fund" was either silently dropped
or corrupted into a fake expense category before `IntakeAgent` (or `BudgetAnalysisAgent`) ever saw
it, causing false-positive clarification requests even when the user had already answered. Fixed by
adding a `notes` field to `TransactionFetcherAgent`'s output instruction — free-text context
preserved verbatim, never folded into `expenses`. Also tightened `skills/intake-clarification/SKILL.md`
(added an explicit "credit a plain-sentence answer even without a matching field name" step) after
observing the model ask about an already-stated emergency fund. Both fixes verified by rerunning the
same failing scenario until it passed.

**`SavingsStrategy.EmergencyFund.existing_investment_accounts` schema addition — skipped, not
needed**: originally planned to fix "emergency-fund sizing always assumes zero," but the `notes`
field fix above already lets `SavingsStrategyAgent` pick up "$12,000 existing emergency fund"
descriptively via `{budget_analysis}` (`BudgetAnalysisAgent` mentions it in its output text, having
seen it in `{raw_transactions}`) — verified this actually reconciled `current_amount` correctly in a
live test. Add the formal structured field later only if eval or real usage shows the descriptive
path is unreliable.

**Frontend (`frontend/main.py`)**: `Runner(agent=root_agent, ...)` → `Runner(app=app, ...)` (`app`
imported under the alias `adk_app` to avoid colliding with the FastAPI instance, itself renamed
`fastapi_app` internally but still exported as module-level `app` for `uvicorn frontend.main:app`).
`session_id` persists via a server-side `_pending: dict[session_id -> {interrupt_id, message}]` plus
a hidden form field (no cookie needed since the question form already round-trips `session_id`).
`/analyze` starts a session and runs the first turn; `/resume` builds the `function_response`
`Content` and runs the next turn; both share a `_run_turn()` helper that inspects the event stream
for an `adk_request_input` function-call (pause) vs. plain text (done) and renders accordingly.

**Phase 2 verification — done, not just planned**: verified via direct `Runner(app=app, ...)` smoke
tests (bypassing `agents-cli run`/`eval`, which don't fully support `Workflow` root agents yet — see
Eval backlog) covering: (1) the standing worked example (car loan + student loan, vague categories,
unexplained surplus) → 2 rounds of clarification → cap correctly triggers full analysis; (2) a
fully-detailed request with no ambiguity → 0 rounds, straight to analysis; (3) `skip_remaining=True`
on round 0 → immediately proceeds to analysis. Also verified the actual frontend end-to-end over
real HTTP (`curl` against a running `uvicorn` dev server): pause → resume → follow-up pause →
resume → cap reached → full analysis rendered, matching the direct-Runner behavior exactly. Also
re-verified all three deterministic Phase 1 metrics (`budget_categories_valid`,
`savings_debt_boundary_valid`, `savings_reconciliation_valid`) still score 1 by feeding a captured
trace's events into each metric's `evaluate()` directly (see Eval backlog for why `agents-cli eval
generate` itself can't be used here yet).

**Files touched**: `app/agent.py` (Workflow/@node restructure, new schemas, `intake_agent`,
`intake_loop`, `TransactionFetcherAgent`'s `notes` field), new
`skills/intake-clarification/SKILL.md`, `frontend/main.py` (session persistence, resume flow),
`AGENTS.md`/`.agents-cli-spec.md` (architecture diagram + the new eval-tooling-gap note),
`tests/eval/datasets/basic-dataset.json` (reworded prompt so it doesn't trip the intake loop, same
categories/amounts).

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
