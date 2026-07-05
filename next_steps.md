# Next Steps

**Status as of this writing**: 4-agent pipeline (`TransactionFetcherAgent` → `BudgetAnalysisAgent` →
`SavingsStrategyAgent` → `DebtReductionAgent`) built, smoke-tested, and eval-tested (1 regression
case passing: `budget_categories_valid`). Minimal local web frontend (`frontend/main.py`) built and
verified end-to-end. Not yet done: Critic → Refiner loop, `threat_model.md`, deployment.

---

## Eval backlog

- **Surplus / `savings_categories` case**: `BudgetAnalysisAgent` now computes `total_surplus`
  (`monthly_income − total_expenses`) and categorizes it into `savings_categories` (default
  `"Spare Change"` entry, 100% of the surplus) instead of folding it into `spending_categories`.
  Verified once by hand (income 5000, expenses 3200 → `total_surplus: 1800`,
  `savings_categories: [{"category": "Spare Change", "amount": 1800, "percentage": 100}]`), but no
  eval case covers it yet. Add one asserting: (1) `savings_categories` sums to 100% of
  `total_surplus`, (2) no surplus/spare-change entry ever appears in `spending_categories`, (3) a
  deficit scenario (expenses ≥ income) produces an empty `savings_categories`, not a negative one.

## Next: Critic → Refiner loop

Not started — plan only, written here before implementation per SDD.

1. **Two new agents**, appended after `DebtReductionAgent` in the pipeline:
   - `CriticAgent` — reviews the coordinator's combined output (budget + savings + debt) against
     the same invariants already in `AGENTS.md`/`SKILL.md` files (percentages sum to 100%, no
     fabricated figures, no investment advice, recommendations don't exceed available cash flow)
     and produces a pass/fail + list of specific issues.
   - `RefinerAgent` — if the critic found issues, revises the flagged output; if not, passes it
     through unchanged.
2. **Orchestration**: wrap in ADK's `LoopAgent` (not `SequentialAgent`) with a `max_iterations` cap
   (e.g. 2-3) and an escalation condition so it stops once the critic passes — this is the actual
   "iterative refinement" pattern the course checklist wants, not just two more agents bolted on.
3. **New `SKILL.md`** for the critic's review criteria (mirrors the 3 analysis skills' anti-patterns
   as its checklist). The refiner can likely stay a plain instruction since its job is narrow ("fix
   exactly what the critic flagged").
4. **Eval impact**: at least one new eval case that deliberately produces a bad first-pass output
   and asserts the loop catches and fixes it — otherwise there's no proof the loop does anything.
5. **Open decision, not yet made**: does the critic re-check the *whole* 3-part output every
   iteration, or only the specific field it flagged last time? Whole-output re-check is simpler and
   more correct; scoped re-check is cheaper (fewer tokens/LLM calls) but risks missing a fix's side
   effects on another section. Resolve this before writing the critic's `SKILL.md`.

---

## After the Critic/Refiner loop

- `threat_model.md` (STRIDE-style, per `.agents-cli-spec.md` → Constraints & Safety Rules).
- `agents-cli scaffold enhance . --deployment-target agent_runtime`, then `agents-cli deploy`
  (decision 6, already locked).
