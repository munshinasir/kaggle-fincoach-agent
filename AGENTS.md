# Coding Agent Guide

## Project: financial-coach-agent

Multi-agent financial coach. See `.agents-cli-spec.md` for the full spec (overview, constraints,
success criteria). Summary:

**Pipeline** (`app/agent.py`, `Workflow`/`@node` — v2 Phase 3, feature-complete; see
`.agents-cli-spec.md` and `next_steps.md` for the full v2 history):

```
FinanceCoachWorkflow (Workflow, resumability_config=ResumabilityConfig(is_resumable=True))
 ├─ START → TransactionFetcherAgent  (tools=[McpToolset(...)], plain text output — a single-
 │                            responsibility choice, not a technical requirement: output_schema
 │                            and tool-calling can coexist in the installed google-adk 2.3.0)
 │                            → state['raw_transactions'] (includes a `notes` field for any
 │                              free-text context — surplus destination, existing emergency fund/
 │                              investment accounts — that doesn't fit income/expenses/debts;
 │                              never dropped, never folded into `expenses`)
 ├─ → intake_loop            (@node(rerun_on_resume=True), async generator; bounded to
 │                            MAX_INTAKE_ROUNDS=2). Calls IntakeAgent (output_schema=
 │                            IntakeAssessment) via ctx.run_node() each round; if it flags
 │                            needs_clarification, yields RequestInput (pauses the run — the
 │                            client resumes with a function_response Content part addressed to
 │                            the same interrupt_id, validated against IntakeAnswer). Stops on:
 │                            IntakeAgent says nothing's outstanding, the user sets
 │                            skip_remaining=True, or the round cap is hit. Always writes
 │                            state['enriched_intake'] (EnrichedIntake) before falling through —
 │                            analysis_pipeline's SequentialAgent doesn't consume node_input
 │                            directly, so the handoff goes through state, same as every other
 │                            agent below.
 ├─ → analysis_pipeline      (SequentialAgent — drops into a Workflow edge unchanged; a plain
 │                            BaseAgent auto-wraps as an AgentNode)
 │    ├─ BudgetAnalysisAgent      (output_schema=BudgetAnalysis)
 │    │                            reads {raw_transactions}, {enriched_intake} + user-provided
 │    │                            income/dependants/manual expenses
 │    │                            → state['budget_analysis']  (spending_categories,
 │    │                              savings_categories, spending_analysis — descriptive only,
 │    │                              acknowledgments — positive callouts, savings_rate)
 │    ├─ SavingsStrategyAgent     (output_schema=SavingsStrategy)
 │    │                            reads {budget_analysis}; owns prescriptive spending-cut +
 │    │                            savings-allocation recommendations (each tagged `type`:
 │    │                            `"spending_cut"` frees up new money, excluded from the
 │    │                            reconciliation identity; `"allocation"` spends
 │    │                            discretionary_surplus, included), intent-branches on
 │    │                            savings_rate/emergency fund, analyzes (never prescribes) debt
 │    │                            via debt_context handoff
 │    │                            → state['savings_strategy']
 │    ├─ DebtReductionAgent       (output_schema=DebtReduction)
 │    │                            reads {budget_analysis}, {savings_strategy} (incl.
 │    │                            debt_context) + user-provided debts; owns all debt
 │    │                            prescriptions and the invest-vs-payoff split (vehicle-level
 │    │                            investing only, never a specific pick)
 │    │                            → state['debt_reduction']
 │    └─ OverallPictureAgent      (output_schema=OverallPicture)
 │                                 reads {budget_analysis}, {savings_strategy}, {debt_reduction};
 │                                 merges into one prioritized, affirming "next steps" list — no
 │                                 new analysis
 │                                 → state['overall_picture']
 └─ → critique_refine_loop   (LoopAgent, max_iterations=MAX_CRITIQUE_ROUNDS=3 — a plain
                              BaseAgent, drops into a Workflow edge unchanged)
      ├─ CriticAgent              (output_schema=CriticVerdict) — independently re-derives every
      │                            percentage/reconciliation number rather than trusting upstream's
      │                            stated values; checks realism ceilings, debt-minimum-payment
      │                            safety, and tone across all four documents
      │                            → state['critic_verdict'] {approved, issues[]}
      ├─ EscalationChecker        (plain `BaseAgent`, no LLM) — reads state['critic_verdict'];
      │                            yields `Event(actions=EventActions(escalate=True))` when
      │                            approved, which stops the LoopAgent immediately (skips
      │                            RefinerAgent/BundleUnpacker that iteration) — verified against
      │                            installed `agents/loop_agent.py` source: LoopAgent checks
      │                            `event.actions.escalate` after every sub-agent event
      ├─ RefinerAgent             (output_schema=RefinedBundle; only runs when not approved) —
      │                            applies each CriticIssue's suggested_fix precisely; every
      │                            untouched field must be copied forward verbatim (narrow patch,
      │                            not a rewrite) → state['refined_bundle']
      └─ BundleUnpacker           (plain `BaseAgent`, no LLM) — redistributes refined_bundle's
                                   four documents back into state['budget_analysis'] etc. via
                                   `actions.state_delta`, since `output_key` only ever writes one
                                   key and CriticAgent's next-iteration re-check reads the four
                                   individual keys
```

This project pins `google-adk>=2.0.0,<3.0.0` (installed: 2.3.0). It uses `Agent`/`SequentialAgent`/
`LoopAgent`/`BaseAgent`/`Workflow` with `output_schema`/`output_key` for structured, state-passing
output, served via the generated `app/fast_api_app.py` + `app_utils/` (do not hand-edit those).
Verify any ADK API usage against the installed `google-adk` package or `/google-agents-cli-adk-code`
— never assume an API shape from memory; the Workflow/HITL wiring here (the exact resume-message
shape, `ctx.resume_inputs` population, `response_schema` validation) and the LoopAgent
escalate/EscalationChecker pattern were both verified by reading the installed source directly
(`workflow/utils/_workflow_hitl_utils.py`, `workflow/utils/_rehydration_utils.py`,
`agents/loop_agent.py`), not from docs alone. Note: `SequentialAgent`/`LoopAgent` are `@deprecated`
in 2.3.0 ("use Workflow instead") but still functional — `analysis_pipeline` and
`critique_refine_loop` keep them since neither needs graph-level conditional routing; only the
intake stage, which needs a conditional/looping HITL interrupt, uses `Workflow`/`@node` directly.

**Known eval-tooling gap**: `agents-cli eval generate` (via the Vertex eval SDK's
`client.evals.run_inference`) does not yet support a `Workflow`-typed root agent — it crashes with
`AttributeError: 'str' object has no attribute 'get'` in `_inference_runner.py`'s
`_extract_new_events_from_partial`, regardless of whether the run pauses on an intake interrupt.
This reproduces on the current `google-agents-cli` 1.0.0 / `google-adk` 2.3.0 pairing; the
`_patch_eval_tool_introspection` docstring in that same file suggests Vertex's eval SDK was written
against `SequentialAgent`-style workflow agents before ADK's newer `Workflow` graph class existed.
Do not attempt to patch `agents-cli`'s vendored script — verify Phase 2+ behavior instead by running
the agent directly with `Runner(app=app, ...)` (see `next_steps.md`'s smoke-test pattern) and, for
the three deterministic Phase 1 metrics, feeding the resulting session events into
`tests/eval/*_metric.py`'s `evaluate()` by hand. Revisit `agents-cli eval generate` after an
`agents-cli`/`google-adk` upgrade.

**Invariants** (see `.agents-cli-spec.md` → Constraints & Safety Rules for the full list):
- Never fabricate a financial figure not derivable from input or transaction data.
- No specific stock/fund/asset picks — vehicle/category-level investing only (e.g. "a low-cost
  index fund"), and only from `debt-reduction`, informed by the invest-vs-payoff threshold logic.
- Spending category percentages must sum to 100% (of `total_expenses`); savings category
  percentages must sum to 100% of `total_surplus`.
- Never recommend reducing or skipping a minimum/regular debt payment, for any reason.
- No persistent storage of income/debt/personal data — in-memory session only for MVP.

**Skills**: each analysis agent's instruction lives in `skills/<name>/SKILL.md`, not inline —
`intake-clarification`, `budget-analysis`, `savings-strategy`, `debt-reduction`, `overall-picture`,
`critic`, `refiner`. `TransactionFetcherAgent`'s instruction is trivial (call the tool, pass through
the result) and stays inline. `EscalationChecker`/`BundleUnpacker` are plain Python `BaseAgent`
subclasses with no LLM and no skill — their logic is the whole implementation.

**Ownership chain** (the core architectural rule extended through Phase 1 — see `next_steps.md` for
the full v2 requirements this implements): `budget-analysis` only describes, never prescribes;
`savings-strategy` prescribes spending/savings actions but only *analyzes* debt (via `debt_context`);
`debt-reduction` owns every debt and invest-vs-payoff prescription; `overall-picture` merges, never
adds new analysis; `critic` only flags problems, never fixes or adds recommendations; `refiner` only
applies exactly what `critic` flagged, never re-derives or restyles anything else. If you're tempted
to add a recommendation to the "wrong" agent, it belongs
downstream instead.

---

## Prerequisites

Install the CLI (one-time):
```bash
uv tool install google-agents-cli
```

---

## Development Phases

### Phase 1: Understand Requirements
Before writing any code, understand the project's requirements, constraints, and success criteria.

### Phase 2: Build and Implement
Implement agent logic in `app/`. Use `agents-cli playground` for interactive testing. Iterate based on user feedback.

### Phase 3: The Evaluation Loop (Main Iteration Phase)
Start with 1-2 eval cases, run `agents-cli eval generate`, then `agents-cli eval grade`, iterate by making changes and rerunning both commands until satisfied. Expect 5-10+ iterations. Once you have a baseline, reach for `agents-cli eval compare` (regression diffs), `agents-cli eval analyze` (cluster failure modes), and `agents-cli eval optimize` (auto-tune prompts). See the **Evaluation Guide** for metrics, dataset schema, LLM-as-judge config, and common gotchas.

### Phase 4: Pre-Deployment Tests
Run `uv run pytest tests/unit tests/integration`. Fix issues until all tests pass.

### Phase 5: Deploy to Dev
**Requires explicit human approval.** Run `agents-cli deploy` only after user confirms. See the **Deployment Guide** for details.

### Phase 6: Production Deployment
Ask the user: Option A (simple single-project) or Option B (full CI/CD pipeline with `agents-cli infra cicd`).

## Development Commands

| Command | Purpose |
|---------|---------|
| `agents-cli playground` | Interactive local testing |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests |
| `agents-cli eval dataset synthesize` | Synthesize multi-turn eval scenarios for your agent |
| `agents-cli eval generate` | Run agent on eval dataset, produce traces |
| `agents-cli eval grade` | Run agent evaluations on the traces |
| `agents-cli eval compare` | Compare two grade-results files (regression check) |
| `agents-cli eval analyze` | Cluster failure modes from grade results |
| `agents-cli eval metric list` | List built-in metrics available in the SDK |
| `agents-cli eval optimize` | Auto-tune agent prompts using eval data |
| `agents-cli lint` | Check code quality |
| `agents-cli infra single-project` | Set up project infrastructure (Terraform) |
| `agents-cli deploy` | Deploy to dev |
| `agents-cli scaffold enhance` | Add deployment target or CI/CD to project |
| `agents-cli scaffold upgrade` | Upgrade project to latest version |

---

## Operational Guidelines for Coding Agents

- **Code preservation**: Only modify code directly targeted by the user's request. Preserve all surrounding code, config values (e.g., `model`), comments, and formatting.
- **NEVER change the model** unless explicitly asked.
- **Model 404 errors**: Fix `GOOGLE_CLOUD_LOCATION` (e.g., `global` instead of `us-east1`), not the model name.
- **ADK tool imports**: Import the tool instance, not the module: `from google.adk.tools.load_web_page import load_web_page`
- **Run Python with `uv`**: `uv run python script.py`. Run `agents-cli install` first.
- **Stop on repeated errors**: If the same error appears 3+ times, fix the root cause instead of retrying.
- **Terraform conflicts** (Error 409): Use `terraform import` instead of retrying creation.
