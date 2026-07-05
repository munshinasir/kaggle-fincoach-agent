# Coding Agent Guide

## Project: financial-coach-agent

Multi-agent financial coach. See `.agents-cli-spec.md` for the full spec (overview, constraints,
success criteria). Summary:

**Pipeline** (`app/agent.py`, `SequentialAgent` — Phase 1 of the v2 plan; Phase 2 wraps this in a
`Workflow`, see `.agents-cli-spec.md` and `next_steps.md` for the full v2 roadmap):

```
FinanceCoordinatorAgent
 ├─ TransactionFetcherAgent  (tools=[McpToolset(...)], plain text output — a single-responsibility
 │                            choice, not a technical requirement: output_schema and tool-calling
 │                            can coexist in the installed google-adk 2.3.0)
 │                            → state['raw_transactions']
 ├─ BudgetAnalysisAgent      (output_schema=BudgetAnalysis)
 │                            reads {raw_transactions} + user-provided income/dependants/manual expenses
 │                            → state['budget_analysis']  (spending_categories, savings_categories,
 │                              spending_analysis — descriptive only, acknowledgments — positive
 │                              callouts, savings_rate)
 ├─ SavingsStrategyAgent     (output_schema=SavingsStrategy)
 │                            reads {budget_analysis}; owns prescriptive spending-cut + savings-
 │                            allocation recommendations, intent-branches on savings_rate/emergency
 │                            fund, analyzes (never prescribes) debt via debt_context handoff
 │                            → state['savings_strategy']
 ├─ DebtReductionAgent       (output_schema=DebtReduction)
 │                            reads {budget_analysis}, {savings_strategy} (incl. debt_context) +
 │                            user-provided debts; owns all debt prescriptions and the invest-vs-
 │                            payoff split (vehicle-level investing only, never a specific pick)
 │                            → state['debt_reduction']
 └─ OverallPictureAgent      (output_schema=OverallPicture)
                              reads {budget_analysis}, {savings_strategy}, {debt_reduction}; merges
                              into one prioritized, affirming "next steps" list — no new analysis
                              → state['overall_picture']
```

This project pins `google-adk>=2.0.0,<3.0.0` (installed: 2.3.0). It uses `Agent`/`SequentialAgent`
from `google.adk.agents` with `output_schema`/`output_key` for structured, state-passing output,
served via the generated `app/fast_api_app.py` + `app_utils/` (do not hand-edit those). Verify any
ADK API usage against the installed `google-adk` package or `/google-agents-cli-adk-code` — never
assume an API shape from memory. Note: `SequentialAgent` is `@deprecated` in 2.3.0 ("use Workflow
instead") — still functional, kept for Phase 1, migrating to `Workflow`/`@node` in Phase 2.

**Invariants** (see `.agents-cli-spec.md` → Constraints & Safety Rules for the full list):
- Never fabricate a financial figure not derivable from input or transaction data.
- No specific stock/fund/asset picks — vehicle/category-level investing only (e.g. "a low-cost
  index fund"), and only from `debt-reduction`, informed by the invest-vs-payoff threshold logic.
- Spending category percentages must sum to 100% (of `total_expenses`); savings category
  percentages must sum to 100% of `total_surplus`.
- Never recommend reducing or skipping a minimum/regular debt payment, for any reason.
- No persistent storage of income/debt/personal data — in-memory session only for MVP.

**Skills**: each analysis agent's instruction lives in `skills/<name>/SKILL.md`, not inline —
`budget-analysis`, `savings-strategy`, `debt-reduction`, `overall-picture`. `TransactionFetcherAgent`'s
instruction is trivial (call the tool, pass through the result) and stays inline.

**Ownership chain** (the core architectural rule extended through Phase 1 — see `next_steps.md` for
the full v2 requirements this implements): `budget-analysis` only describes, never prescribes;
`savings-strategy` prescribes spending/savings actions but only *analyzes* debt (via `debt_context`);
`debt-reduction` owns every debt and invest-vs-payoff prescription; `overall-picture` merges, never
adds new analysis. If you're tempted to add a recommendation to the "wrong" agent, it belongs
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
