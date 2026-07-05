# Next Steps

**Status as of this writing**: v2 plan approved (full plan: `/home/nasir/.claude/plans/floofy-shimmying-hellman.md`,
3 phases). Step 0 (git checkpoint) done. **Phase 1 (ownership chain, tone, final synthesis) done and
eval-tested** — 5-agent pipeline (`TransactionFetcherAgent` → `BudgetAnalysisAgent` →
`SavingsStrategyAgent` → `DebtReductionAgent` → `OverallPictureAgent`), 4 eval metrics passing
(`custom_response_quality`, `budget_categories_valid`, `savings_debt_boundary_valid`,
`savings_reconciliation_valid`). Not started: Phase 2 (Workflow/@node migration + intake loop),
Phase 3 (Critic/Refine with the realism rubric), `threat_model.md`, deployment.

---

## Design decision: investing vs. debt payoff threshold (resolved 2026-07-05)

Tested against the worked example (0.99% car loan, 5.99% student loan, $1000-1550/mo surplus
depending on scenario): `debt-reduction`'s threshold-based instruction (all above-threshold debt
paid first, investing only once no debt exceeds the threshold) resulted in zero investing
allocation in every test run at a 6% threshold — the 5.99% loan sat just under the cutoff but the
model kept prioritizing it over investing anyway (in one run, correctly noticing the loan's minimum
payment doesn't even cover accruing interest — a well-reasoned override, not a bug). Requirement 7's
"invest *in proportion to* reducing debt" reads more like a blended split than a strict cutoff, but
**decision: keep the sequential threshold approach, raise it from 6% to 8%** — revisit only if
real usage shows it still never triggers investing. No proportional-split logic planned for now.

## Eval backlog

- **Cut-vs-allocation reconciliation nuance**: `savings_reconciliation_valid` (added in Phase 1)
  checks `sum(recommendations[].amount) + debt minimums + available_surplus_after_savings ==
  total_surplus`. This holds for the current formal eval case (no spending cuts recommended, since
  savings_rate was ≥20% with no stated emergency fund exception triggering cuts only for that
  reason). It does **not** yet correctly handle the case where `recommendations` includes a
  spending-cut entry — a cut is additive to the allocatable pool, not consumptive from it, and the
  schema doesn't currently distinguish cut-type from allocation-type recommendations. Confirmed by
  hand against the worked example (car loan/student loan scenario), which does trigger cuts. Needs
  either a `type: "spending_cut" | "allocation"` field on `SavingsRecommendation` or a smarter
  metric — decide during Phase 3 when the Critic's own rubric needs the same reconciliation logic
  anyway.
- **Surplus / `savings_categories` case**: `BudgetAnalysisAgent` computes `total_surplus` and
  categorizes it into `savings_categories` (default `"Spare Change"` entry). Verified by hand, not
  yet eval-covered: (1) `savings_categories` sums to 100% of `total_surplus`, (2) no surplus/
  spare-change entry ever appears in `spending_categories`, (3) a deficit scenario (expenses ≥
  income) produces an empty `savings_categories`, not a negative one.

---

## Phase 2 — Intake/Clarification loop (Workflow/@node migration)

See the approved plan file for the full design (verified against installed `google-adk==2.3.0`
source): migrate `root_agent` to a `Workflow` with `transaction_fetcher_agent → intake_loop →
analysis_pipeline` (the existing 5-agent `SequentialAgent`, unchanged). New `IntakeAgent` +
`skills/intake-clarification/SKILL.md`, bounded to 2 rounds, with a "proceed anyway" escape hatch.
Frontend needs persistent `session_id` across requests and resume-turn handling (function_response,
not plain text). Full file list and schema additions are in the plan file — don't re-derive them.

## Phase 3 — Critic + Refine loop

Wraps `OverallPictureAgent`'s output in `LoopAgent(sub_agents=[CriticAgent, RefinerAgent],
max_iterations=3)`. Concrete rubric (from the approved plan): percentages sum to 100%; no
single-category cut exceeds ~30-50% unless savings_rate ≈ 0%; no recommendation reduces/skips a
minimum debt payment; tone is affirming. Add the cut-vs-allocation reconciliation logic here too
(see Eval backlog above) since the Critic needs it regardless of whether the schema changes.

## After Phase 3

- `threat_model.md` (STRIDE-style, per `.agents-cli-spec.md` → Constraints & Safety Rules).
- `agents-cli scaffold enhance . --deployment-target agent_runtime`, then `agents-cli deploy`.
