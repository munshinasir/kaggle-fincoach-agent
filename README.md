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

One Google ADK `Workflow` graph, not a fixed pipeline — real conditional routing, not just a
straight line:

```
user message / uploaded documents
        │
        ▼
TransactionFetcherAgent   (normalizes text / MCP / PDFs)
        │
        ▼
security_checkpoint       (deterministic PII scrub + injection removal)
        ├── halted ──────────────────► halted_node (stop)
        └── clean
                │
                ▼
        intake_loop        (IntakeAgent decides, each round)
                ├── ask ───────────────► back to intake_loop
                ├── conversational ────► conversational_node (friendly nudge)
                ├── blocked ───────────► no_action_node ("can't help yet")
                └── analysis
                        │
                        ▼
                analysis_pipeline    (agent breakdown below)
                        │
                        ▼
                critique_refine_loop  (the crown jewel — below)
                        │
                        ▼
                final bundle → rendered as prose in the chat UI
```

Zooming into `analysis_pipeline` itself:

```
BudgetAnalysisAgent
   → classifies + quantifies spending
        │
        ▼
SavingsStrategyAgent
   → builds the savings plan
        │
        ▼
DebtReductionAgent
   → builds the debt payoff plan
        │
        ▼
OverallPictureAgent
   → merges into one prioritized plan
```

The reasoning behind this split matters more than the boxes themselves. Budget analysis's entire
job is to classify every dollar of spending into clear categories and compute the shared numbers —
total expenses, surplus, savings rate — that both savings strategy and debt reduction build
directly on top of; keeping that work focused on classification and alignment means the two agents
reading its output are always working from the same accurate, consistent foundation. Savings
strategy's job is savings and spending-cut actions specifically; whenever the money in question
might instead go toward debt, that decision belongs to debt reduction, the one agent with the full
picture of every balance and interest rate needed to make it well. That division of labor is
exactly what let a real contradiction bug — savings recommending an index fund while debt reduction
wanted that same money for a 22%-APR card — get resolved in one place instead of untangling two
agents' logic.

The crown jewel is the loop that runs after all four agents finish:

```
                 ┌─────────────────────────────────┐
                 │                                 │
                 ▼                                 │
           CriticAgent   ──approved?── No ──► RefinerAgent
     (re-derives every number,             (applies exactly the
      consolidates the bundle)              flagged fixes)
                 │
                Yes
                 │
                 ▼
        final, signed-off bundle
     (capped at 3 rounds — ships the
      most recent draft with an honest
      caveat once the cap is reached)
```

- **Why it's needed**: four separate agents each produce their own numbers and recommendations —
  without a coordinating step, two well-reasoned agents can still land on guidance that quietly
  competes for the same dollars. Finance already touches nearly everyone's daily life, and most
  people working through it are doing so without a finance background; they deserve one clear set
  of action items, not two agents talking past each other.
- **What role it plays**: the critic's job goes beyond checking arithmetic — it consolidates all
  four documents into one coherent view, catching exactly the kind of overlapping or contradictory
  guidance described above before it ever reaches the user. That coordination is what lets every
  other agent stay focused entirely on its own area: budget analysis stays focused purely on
  spending, savings strategy stays focused purely on savings, because the critic is the single
  place that reconciles them.
- **Why it's bounded**: capped at 3 rounds so the loop keeps working toward agreement instead of
  running indefinitely; if it reaches that cap, the user still gets the most recent draft, clearly
  labeled, rather than nothing at all.

**Why agents, and why sequential.** Isolating responsibility this way means a mistake or scope
creep in one agent's job stays contained to that agent's own output — it's what lets the critic
cleanly arbitrate between exactly-known contributions instead of untangling a single monolithic
prompt. The pipeline is sequential, not parallel, because each stage's output is a genuine input to
the next — savings math needs the budget numbers first, debt decisions need the savings context
first — a real dependency chain, not an arbitrary ordering choice. Each node has its own job,
defined by what it reads and what it produces:

- **`TransactionFetcherAgent`** takes in whatever the user provides — typed text, transactions
  pulled through the MCP tool, or one or more uploaded PDF statements (bank, mortgage, utility,
  credit card). It identifies each document's type, extracts income from deposits, places each
  expense into its own labeled category, and reconciles every debt's balance, interest rate, and
  minimum payment — matching a bank-statement debit against that debt's own statement so a payment
  is captured exactly once. It outputs one compact, consistent JSON object (income, expenses by
  category, debts, notes) that every agent after it can rely on, however varied the original input
  was.
- **`security_checkpoint`** takes that JSON and runs it through a deterministic, regex-based scrub
  for SSNs, account numbers, and card numbers, plus a check for prompt-injection phrasing. Because
  this step is plain Python rather than a model call, the same input always produces the same
  protection — the trust layer everything downstream builds on.
- **`IntakeAgent`** reads the normalized financial picture together with any clarifying answers
  gathered so far, and decides what happens next: ask one more combined question, proceed straight
  to analysis, respond to input that's purely conversational, or recognize that there's genuinely
  no income or savings yet to plan around. It's the readiness gate that makes sure everything after
  it runs on a financial picture that's actually ready to be analyzed.
- **`BudgetAnalysisAgent`** reads the normalized income, expenses, and debts, categorizes every
  expense, and computes the shared numbers the rest of the pipeline is built on: total expenses,
  monthly surplus, savings rate, spending percentages by category, and genuine positive callouts
  where the numbers earn them. This classification-and-alignment work gives savings strategy and
  debt reduction one accurate foundation to reason from.
- **`SavingsStrategyAgent`** reads the budget analysis and turns it into a concrete plan: how large
  an emergency fund should be, specific savings and spending-cut recommendations, and automation
  techniques to make them stick. It also computes a debt-context handoff — leftover surplus,
  debt-to-income ratio, whether an emergency fund already exists — so debt reduction has exactly
  what it needs to decide what happens to that same money.
- **`DebtReductionAgent`** reads the budget analysis and the savings strategy's debt context, then
  builds the full payoff picture: avalanche and snowball plans for every debt, and the
  invest-vs-payoff decision for whatever surplus remains. It's the most complex reasoning step in
  the pipeline, and the one agent with the complete picture needed to make that call well.
- **`OverallPictureAgent`** reads all three outputs above and merges them into the single,
  prioritized plan the user actually sees — the wins worth celebrating, and one ordered list of
  next steps that folds savings and debt recommendations together into a single coherent plan.
- **`CriticAgent`** reads the full bundle and independently re-derives every number from scratch,
  while consolidating all four documents into one coherent view — catching the cases where two
  agents' guidance would otherwise compete for the same dollars. That coordination is what keeps
  every other agent free to stay focused entirely on its own area.
- **`RefinerAgent`** reads the critic's specific, itemized findings and applies exactly those fixes
  to the bundle, carrying every untouched field forward exactly as it was. A fix stays a fix —
  precise and traceable — rather than turning into a full rewrite.

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
