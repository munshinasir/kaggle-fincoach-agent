# Financial Coach Agent

A multi-agent AI financial coach that turns a plain-language description of your income, spending,
debts, and savings goals — typed or uploaded as bank/credit-card/utility statements — into a
complete, judgment-free financial picture: a budget breakdown, a savings strategy, and a debt
payoff plan, cross-checked for arithmetic and safety before you ever see it.

Built for the Kaggle 5-Day AI Agents Intensive Vibe Coding Capstone — **Concierge Agents** track.

## Problem

Personal financial planning is one of the most common "I should really deal with this" tasks people
put off — not because the math is hard, but because it requires pulling together income, scattered
expenses, debts, and savings goals into one coherent plan, and most people don't know where to
start or whether the advice they'd get is actually sound for their numbers. A concierge-style agent
that can take messy, real-world financial input (typed or straight from statements), ask only the
clarifying questions that actually matter, and produce a plan it has independently checked for
errors, is exactly the kind of personal-assistant use case agents are suited for — but it also
touches genuinely sensitive personal data (income, account numbers, debt), so doing it safely is
part of the problem, not an afterthought.

## Solution

A financial coach that:
- Accepts typed descriptions **or** uploaded PDF statements (bank, mortgage, utility, credit card),
  reconciling them into one financial picture without double-counting a payment that appears on both
  a bank statement and its own card/mortgage statement.
- Screens every input for PII (SSNs, account numbers, card numbers) and prompt-injection attempts
  *before* any other agent sees it — deterministically, not by asking an LLM to behave.
- Asks at most two rounds of clarifying questions, only when something would actually change the
  analysis (a vague spending category, an unexplained surplus, missing emergency-fund info) —
  and refuses to run a full analysis on pure chit-chat or on confirmed zero-income/no-savings input,
  rather than producing a nonsense $0-income plan.
- Produces a budget breakdown, a savings strategy, and an avalanche/snowball debt payoff plan, each
  owned by a single specialized agent so no agent second-guesses another's job.
- Runs the whole bundle through an independent critic that re-derives every number itself and a
  refiner that applies only the critic's specific fixes — up to 3 rounds — before anything reaches
  the user.
- Presents the result as calm, plain-English prose with bolded numbers in a Claude-Web-inspired chat
  UI, not a wall of JSON.

## Architecture

```mermaid
flowchart TD
    START([user message / uploaded documents])
    TF[TransactionFetcherAgent<br/><i>normalizes text / MCP / PDFs</i>]
    SEC{security_checkpoint<br/><i>deterministic PII scrub +<br/>injection-phrase removal</i>}
    HALT[halted_node]
    INTAKE{intake_loop<br/><i>IntakeAgent decides:<br/>ask / proceed / conversational / blocked</i>}
    CHAT[conversational_node<br/><i>fixed friendly nudge</i>]
    BLOCK[no_action_node<br/><i>fixed "can't help yet" block</i>]
    PIPE[analysis_pipeline]
    BA[BudgetAnalysisAgent]
    SS[SavingsStrategyAgent]
    DR[DebtReductionAgent]
    OP[OverallPictureAgent]
    LOOP{critique_refine_loop<br/>max 3 iterations}
    CRITIC[CriticAgent<br/><i>re-derives every number</i>]
    CHECK{approved?}
    REFINE[RefinerAgent<br/><i>applies only flagged fixes</i>]
    FINAL([final bundle -> prose UI])

    START --> TF --> SEC
    SEC -- clean --> INTAKE
    SEC -- halted --> HALT
    INTAKE -- ask --> INTAKE
    INTAKE -- conversational --> CHAT
    INTAKE -- blocked --> BLOCK
    INTAKE -- analysis --> PIPE
    PIPE --> BA --> SS --> DR --> OP --> LOOP
    LOOP --> CRITIC --> CHECK
    CHECK -- yes --> FINAL
    CHECK -- no --> REFINE --> CRITIC
```

**Ownership-chain discipline**: `budget-analysis` only describes spending, `savings-strategy` only
prescribes savings/spending cuts (never debt), `debt-reduction` owns every debt and invest-vs-payoff
decision, `overall-picture` only merges and prioritizes, `critic` only flags problems, `refiner` only
applies what was flagged. When two agents' recommendations conflict over the same money (e.g. an
investment allocation competing with an above-threshold debt payoff), the critic — not either
originating agent — is the sole arbiter, and debt always wins that specific conflict.

## Key concepts demonstrated

| Concept | Where |
|---|---|
| **Multi-agent system (ADK `Workflow`)** | `app/agent.py` — 8+ specialized `Agent`s, a `LoopAgent`-based critique/refine cycle, conditional routing edges (`security_checkpoint`, `intake_loop`), and human-in-the-loop `RequestInput`/resume for clarifying and security-confirmation questions |
| **MCP Server** | `app/transactions_mcp_server.py` — exposes a `get_transactions` tool consumed by `TransactionFetcherAgent` |
| **Security features** | `app/agent.py`'s `security_checkpoint` node — deterministic regex-based PII redaction (SSN, credit card, bank account) and prompt-injection phrase stripping, applied uniformly to typed and document-derived input; see `threat_model.md` for the full STRIDE analysis |
| **Agent skills** | `skills/*/SKILL.md` — every analysis agent's instructions live in a versioned skill file (budget-analysis, savings-strategy, debt-reduction, overall-picture, critic, refiner, intake-clarification, transaction-fetcher), loaded at agent-construction time so behavior and documentation never drift apart |

(4 of the 6 course concepts are demonstrated in code above — deployability and Antigravity were
deliberately out of scope for this iteration; the project ships a working `Dockerfile` and
`agents-cli`/Terraform deployment scaffolding if that's of interest.)

## Project Structure

```
financial-coach-agent/
├── app/
│   ├── agent.py                  # The Workflow graph: all agents, schemas, routing
│   └── transactions_mcp_server.py # Stub MCP server (canned sample transactions)
├── skills/                       # One SKILL.md per agent's instructions
│   ├── transaction-fetcher/  ├── intake-clarification/  ├── budget-analysis/
│   ├── savings-strategy/     ├── debt-reduction/         ├── overall-picture/
│   └── critic/                └── refiner/
├── frontend/
│   ├── main.py                   # FastAPI JSON API driving the chat UI
│   ├── presenter.py               # Deterministic (no-LLM) bundle-to-prose-HTML renderer
│   └── static/                    # Vanilla JS/CSS single-page chat UI
├── tests/
│   ├── unit/                      # Pure-function tests (no LLM), real pytest
│   └── smoke/                     # Runnable scripts exercising real Gemini calls
├── threat_model.md                # STRIDE threat model
└── .agents-cli-spec.md            # Living architecture/behavior spec
```

## Setup

Requirements: [`uv`](https://docs.astral.sh/uv/getting-started/installation/), a Gemini API key or a
GCP project with Vertex AI enabled.

```bash
git clone <this-repo-url>
cd financial-coach-agent
uv sync

cp .env.example .env
# edit .env: either set GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT,
# or comment those out and set GEMINI_API_KEY instead
```

Run the chat UI locally:

```bash
uv run uvicorn frontend.main:app --port 8080
```

Open `http://127.0.0.1:8080/` — describe your finances (or upload statement PDFs) and the agent
will ask any clarifying questions it needs before producing your budget/savings/debt picture.

Run the tests:

```bash
uv run pytest tests/unit/                          # fast, deterministic, no LLM calls
uv run python tests/smoke/test_frontend_api_smoke.py  # real Gemini calls, run individually
```

Every script under `tests/smoke/` is a standalone runnable check (not pytest-collected) — see each
file's docstring for what it verifies.

## Security

No API keys or secrets are committed — `.env` is gitignored, only `.env.example` (placeholders) is
tracked. See `threat_model.md` for the full STRIDE-style review of this project's security posture,
including the known, accepted limitation that PII redaction is best-effort for document-derived
text (reliable for typed input) since it depends on whether the document-reading agent happens to
transcribe PII verbatim.

## Status

This is a local development build (not deployed to a public endpoint). All functionality is
demonstrated via the local chat UI and the automated test suite described above.
