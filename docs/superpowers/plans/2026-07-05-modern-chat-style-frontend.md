# Modern-Chat-Style Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `frontend/main.py`'s full-page-reload, raw-JSON local dev UI with a modern-chat-style single-page chat interface that renders the analysis as calm, bolded prose.

**Architecture:** A thin FastAPI JSON API (`frontend/main.py`) drives the existing in-process ADK `Runner`/`Workflow` exactly as today; a new deterministic module (`frontend/presenter.py`, no LLM call) turns the one final analysis bundle into two HTML sections; a static SPA shell (`frontend/static/`) built with vanilla JS `fetch()` renders a scrolling chat transcript with no page reloads.

**Tech Stack:** FastAPI (already a transitive dependency via `google-adk[gcp]`, confirmed importable), Starlette's `StaticFiles`, vanilla JS/CSS/HTML (no framework, no build step, no new Python dependency). This mirrors the Kaggle course's own reference frontend pattern (`Day5/expense-agent/submission_frontend/main.py`: FastAPI + hand-rolled HTML/CSS + vanilla JS `fetch()`).

## Global Constraints

- No changes to `app/agent.py`, any `skills/*.md`, or the intake/security HITL *behavior* — only how those interrupts are displayed changes.
- No new Python dependencies.
- No dark mode, no multi-conversation history/sidebar, no follow-up chat after a final result.
- Visual: single centered column, `max-width: 48rem`; warm off-white background (`#faf9f7`); font stack `ui-sans-serif, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif`; light theme only.
- Interactivity: SPA-lite — one static HTML shell loaded once, vanilla JS `fetch()` calls to `/api/analyze`, `/api/resume`, `/api/resume-security`, no page reload per turn.
- Prose rendering is a **deterministic Python template** (`frontend/presenter.py`) — no LLM call, ever.
- The rendered output is built from **one final bundle**, never four independent state lookups stitched together at render time:
  - If `critique_refine_loop` ran at least one refine pass, the final bundle is `state['refined_bundle']`.
  - If the critic approved on the first pass (no refine pass ran), the final bundle is reconstructed from `state['budget_analysis']`, `state['savings_strategy']`, `state['debt_reduction']`, `state['overall_picture']` — already identical in shape to what a `RefinedBundle` would hold.
- Congratulatory/"wins" content in the rendered output comes **only** from the final bundle's `overall_picture.wins` — never re-derived or duplicated from `budget_analysis.acknowledgments` directly.
- Edge case: if `critic_verdict.approved` is still `false` after `MAX_CRITIQUE_ROUNDS`, render the final bundle anyway, prefaced with exactly this line: `This reflects the most recent draft; it didn't complete a final consistency check.`
- API response shapes, exactly:
  ```
  {"type": "question", "session_id": str, "message": str}
  {"type": "security", "session_id": str, "message": str}
  {"type": "final", "session_id": str, "confirmation_html": str, "recommendations_html": str}
  ```
- No JSON, no critic commentary, no intermediate refiner passes are ever shown to the user.

---

### Task 1: `frontend/presenter.py` — deterministic bundle-to-HTML rendering

**Files:**
- Create: `frontend/presenter.py`
- Test: `tests/unit/test_presenter.py`

**Interfaces:**
- Produces (used by Task 2):
  - `format_money(amount: float | None) -> str`
  - `assemble_final_bundle(state: dict) -> dict` — takes an ADK session-state-shaped dict, returns `{"budget_analysis": dict, "savings_strategy": dict, "debt_reduction": dict, "overall_picture": dict}`
  - `render_confirmation(bundle: dict) -> str` — HTML string
  - `render_recommendations(bundle: dict) -> str` — HTML string
  - `render_final(bundle: dict, approved: bool = True) -> dict[str, str]` — returns `{"confirmation_html": str, "recommendations_html": str}`

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_presenter.py`:

```python
"""Unit tests for frontend/presenter.py — pure, deterministic, no LLM calls.
See docs/superpowers/specs/2026-07-05-modern-chat-style-frontend-design.md
("Output Rendering") for the design this implements.
"""

from frontend.presenter import (
    assemble_final_bundle,
    format_money,
    render_confirmation,
    render_final,
    render_recommendations,
)

SAMPLE_BUNDLE = {
    "budget_analysis": {
        "total_expenses": 2195.0,
        "monthly_income": 5000.0,
        "total_surplus": 2805.0,
        "savings_rate": 0.56,
        "spending_categories": [
            {"category": "Housing", "amount": 1500.0, "percentage": 68.3},
            {"category": "Other", "amount": 695.0, "percentage": 31.7},
        ],
        "spending_analysis": [
            {"category": "Housing", "analysis": "Housing is the largest expense."}
        ],
        "acknowledgments": ["This exact sentence must not appear."],
    },
    "savings_strategy": {
        "emergency_fund": {
            "recommended_amount": 18000.0,
            "current_amount": 0.0,
            "current_status": "Building from zero.",
        },
        "recommendations": [
            {
                "category": "Emergency Fund",
                "amount": 1500.0,
                "rationale": "Build your emergency fund.",
                "type": "allocation",
            },
        ],
        "automation_techniques": [
            {"name": "Auto-transfer", "description": "Move $1,500 to savings on payday."}
        ],
        "debt_context": {
            "debt_to_income_ratio": 0.05,
            "available_surplus_after_savings": 1305.0,
            "has_emergency_fund": False,
            "note": "Surplus available for debt paydown.",
        },
    },
    "debt_reduction": {
        "total_debt": 6000.0,
        "debts": [
            {"name": "Visa", "amount": 2000.0, "interest_rate": 22.0, "min_payment": 150.0},
            {"name": "Mastercard", "amount": 4000.0, "interest_rate": 18.0, "min_payment": 100.0},
        ],
        "payoff_plans": {
            "avalanche": {"total_interest": 220.0, "months_to_payoff": 5, "monthly_payment": 1305.0},
            "snowball": {"total_interest": 235.0, "months_to_payoff": 5, "monthly_payment": 1305.0},
        },
        "recommendations": [
            {
                "title": "Prioritize Debt Over Investing",
                "description": "Pay down the Visa first.",
                "impact": "Debt-free in 5 months.",
            },
        ],
    },
    "overall_picture": {
        "wins": ["Your savings rate is a strong 56%."],
        "next_steps": [
            {
                "category": "Debt",
                "action": "Redirect surplus to the Visa card first.",
                "amount": 1305.0,
                "priority": 1,
            },
            {
                "category": "Emergency Fund",
                "action": "Continue your emergency fund contribution.",
                "amount": 1500.0,
                "priority": 2,
            },
        ],
    },
}


def test_format_money_formats_with_commas_and_two_decimals():
    assert format_money(5000) == "$5,000.00"
    assert format_money(1234.5) == "$1,234.50"


def test_format_money_none_is_not_specified():
    assert format_money(None) == "not specified"


def test_assemble_final_bundle_prefers_refined_bundle():
    state = {"refined_bundle": SAMPLE_BUNDLE, "budget_analysis": {"total_expenses": 1.0}}
    assert assemble_final_bundle(state) == SAMPLE_BUNDLE


def test_assemble_final_bundle_falls_back_to_separate_keys():
    state = {
        "budget_analysis": SAMPLE_BUNDLE["budget_analysis"],
        "savings_strategy": SAMPLE_BUNDLE["savings_strategy"],
        "debt_reduction": SAMPLE_BUNDLE["debt_reduction"],
        "overall_picture": SAMPLE_BUNDLE["overall_picture"],
    }
    assert assemble_final_bundle(state) == SAMPLE_BUNDLE


def test_render_confirmation_bolds_income_expenses_and_surplus():
    result = render_confirmation(SAMPLE_BUNDLE)
    assert "<strong>$5,000.00</strong>" in result
    assert "<strong>$2,195.00</strong>" in result
    assert "<strong>$2,805.00</strong>" in result
    assert "<strong>56%</strong>" in result


def test_render_confirmation_lists_spending_categories():
    result = render_confirmation(SAMPLE_BUNDLE)
    assert "<strong>Housing</strong>" in result
    assert "$1,500.00" in result


def test_render_confirmation_wins_come_only_from_overall_picture():
    result = render_confirmation(SAMPLE_BUNDLE)
    assert "Your savings rate is a strong 56%." in result
    assert "Where you're doing well" in result
    # budget_analysis.acknowledgments must never be read directly — only
    # overall_picture.wins is a valid source of congratulatory content.
    assert "This exact sentence must not appear." not in result


def test_render_recommendations_orders_next_steps_by_priority():
    result = render_recommendations(SAMPLE_BUNDLE)
    debt_pos = result.index("Redirect surplus to the Visa card first.")
    ef_pos = result.index("Continue your emergency fund contribution.")
    assert debt_pos < ef_pos


def test_render_recommendations_includes_debt_payoff_numbers():
    result = render_recommendations(SAMPLE_BUNDLE)
    assert "<strong>5 months</strong>" in result
    assert "$220.00" in result


def test_render_final_returns_both_sections_with_no_raw_json():
    result = render_final(SAMPLE_BUNDLE)
    assert set(result.keys()) == {"confirmation_html", "recommendations_html"}
    assert "Your Financial Picture" in result["confirmation_html"]
    assert "Recommendations" in result["recommendations_html"]
    assert "{" not in result["confirmation_html"]
    assert "{" not in result["recommendations_html"]


def test_render_final_adds_caveat_when_not_approved():
    result = render_final(SAMPLE_BUNDLE, approved=False)
    assert "didn't complete a final consistency check" in result["confirmation_html"]


def test_render_final_omits_caveat_when_approved():
    result = render_final(SAMPLE_BUNDLE, approved=True)
    assert "didn't complete a final consistency check" not in result["confirmation_html"]
```

- [ ] **Step 2: Run the test file to verify it fails**

Run: `uv run pytest tests/unit/test_presenter.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'frontend.presenter'`

- [ ] **Step 3: Write `frontend/presenter.py`**

```python
"""Deterministic, LLM-free rendering of the final analysis bundle into prose HTML.

Turns the four-document bundle (budget_analysis, savings_strategy,
debt_reduction, overall_picture) that critique_refine_loop produces into
two HTML fragments for the frontend — no JSON, no LLM call, so tone and
numbers can never drift from what's already in the approved bundle. See
docs/superpowers/specs/2026-07-05-modern-chat-style-frontend-design.md
("Output Rendering") for the design this implements.
"""

import html


def format_money(amount: float | None) -> str:
    """Formats a dollar amount with thousands separators and 2 decimals.

    Returns "not specified" for None, matching this project's convention
    of never fabricating a number that wasn't in the upstream analysis.
    """
    if amount is None:
        return "not specified"
    return f"${amount:,.2f}"


def assemble_final_bundle(state: dict) -> dict:
    """Returns the one final bundle from ADK session state.

    If critique_refine_loop ran at least one refine pass, state['refined_bundle']
    already nests all four documents as one object — use it directly. If the
    critic approved on the first pass, refiner never ran and there is no
    'refined_bundle' key, but the four separate state keys are already
    identical in shape/content to what a RefinedBundle would hold, so they're
    reassembled into the same shape here. Either way the caller gets one
    bundle-shaped dict, never four independent lookups to reconcile.
    """
    refined = state.get("refined_bundle")
    if refined:
        return refined
    return {
        "budget_analysis": state.get("budget_analysis") or {},
        "savings_strategy": state.get("savings_strategy") or {},
        "debt_reduction": state.get("debt_reduction") or {},
        "overall_picture": state.get("overall_picture") or {},
    }


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def render_confirmation(bundle: dict) -> str:
    """Renders the "Your Financial Picture" section from bundle['budget_analysis']
    and bundle['overall_picture']['wins'] — the confirmation/analysis half of the
    final output. Never reads bundle['budget_analysis']['acknowledgments'] directly;
    congratulatory content comes only from overall_picture.wins.
    """
    budget = bundle.get("budget_analysis") or {}
    overall = bundle.get("overall_picture") or {}

    income = budget.get("monthly_income")
    expenses = budget.get("total_expenses")
    surplus = budget.get("total_surplus")
    savings_rate = budget.get("savings_rate")

    if income is not None:
        opening = (
            f"Your monthly income is <strong>{format_money(income)}</strong>, with total "
            f"expenses of <strong>{format_money(expenses)}</strong>"
        )
        if surplus is not None:
            opening += f" — a surplus of <strong>{format_money(surplus)}</strong>"
            if savings_rate is not None:
                opening += f", a <strong>{savings_rate * 100:.0f}%</strong> savings rate"
        opening += "."
    else:
        opening = f"Your total monthly expenses come to <strong>{format_money(expenses)}</strong>."

    sections = [f"<h2>Your Financial Picture</h2><p>{opening}</p>"]

    categories = budget.get("spending_categories") or []
    if categories:
        items = []
        for cat in categories:
            name = _esc(cat.get("category"))
            amount = format_money(cat.get("amount"))
            pct = cat.get("percentage")
            pct_clause = f" (<em>{pct:.1f}%</em> of expenses)" if pct is not None else ""
            items.append(f"<li><strong>{name}</strong> — {amount}{pct_clause}</li>")
        sections.append("<h3>Spending breakdown</h3><ul>" + "".join(items) + "</ul>")

    analysis = budget.get("spending_analysis") or []
    if analysis:
        items = [
            f"<li><em>{_esc(a.get('category'))}</em>: {_esc(a.get('analysis'))}</li>"
            for a in analysis
        ]
        sections.append("<ul>" + "".join(items) + "</ul>")

    wins = overall.get("wins") or []
    if wins:
        items = "".join(f"<li>{_esc(w)}</li>" for w in wins)
        sections.append(f"<h3>Where you're doing well</h3><ul>{items}</ul>")

    return "".join(sections)


def render_recommendations(bundle: dict) -> str:
    """Renders the "Recommendations" section from bundle['savings_strategy'],
    bundle['debt_reduction'], and bundle['overall_picture']['next_steps'].
    """
    savings = bundle.get("savings_strategy") or {}
    debt = bundle.get("debt_reduction") or {}
    overall = bundle.get("overall_picture") or {}

    sections = ["<h2>Recommendations</h2>"]

    next_steps = sorted(overall.get("next_steps") or [], key=lambda s: s.get("priority", 999))
    if next_steps:
        items = []
        for step in next_steps:
            action = _esc(step.get("action"))
            amount = step.get("amount")
            amount_clause = f" ({format_money(amount)})" if amount is not None else ""
            category = _esc(step.get("category"))
            items.append(f"<li><strong>{action}</strong>{amount_clause} — <em>{category}</em></li>")
        sections.append("<h3>Next steps</h3><ol>" + "".join(items) + "</ol>")

    next_step_categories = {s.get("category") for s in next_steps}

    savings_block = []
    ef = savings.get("emergency_fund") or {}
    if ef:
        recommended = format_money(ef.get("recommended_amount"))
        current = ef.get("current_amount")
        current_clause = (
            f", you currently have <strong>{format_money(current)}</strong>"
            if current is not None
            else ""
        )
        status = _esc(ef.get("current_status"))
        status_clause = f" — {status}" if status else ""
        savings_block.append(
            f"<p>Your recommended emergency fund is <strong>{recommended}</strong>"
            f"{current_clause}{status_clause}.</p>"
        )

    remaining = [
        r
        for r in (savings.get("recommendations") or [])
        if r.get("category") not in next_step_categories
    ]
    if remaining:
        items = []
        for r in remaining:
            category = _esc(r.get("category"))
            amount = format_money(r.get("amount"))
            rationale = r.get("rationale")
            rationale_clause = f": {_esc(rationale)}" if rationale else ""
            items.append(f"<li><strong>{category}</strong> — {amount}{rationale_clause}</li>")
        savings_block.append("<ul>" + "".join(items) + "</ul>")

    automations = savings.get("automation_techniques") or []
    if automations:
        items = "".join(
            f"<li><strong>{_esc(a.get('name'))}</strong>: {_esc(a.get('description'))}</li>"
            for a in automations
        )
        savings_block.append(f"<ul>{items}</ul>")

    if savings_block:
        sections.append("<h3>Savings &amp; emergency fund</h3>" + "".join(savings_block))

    debt_block = []
    debts = debt.get("debts") or []
    if debts:
        items = "".join(
            f"<li><strong>{_esc(d.get('name'))}</strong> — {format_money(d.get('amount'))} "
            f"at {d.get('interest_rate')}% APR</li>"
            for d in debts
        )
        debt_block.append(f"<ul>{items}</ul>")

    plans = debt.get("payoff_plans") or {}
    avalanche = plans.get("avalanche") or {}
    snowball = plans.get("snowball") or {}
    if avalanche and snowball:
        debt_block.append(
            "<p>Following the avalanche method, you'd be debt-free in "
            f"<strong>{avalanche.get('months_to_payoff')} months</strong>, paying "
            f"<strong>{format_money(avalanche.get('total_interest'))}</strong> in interest; "
            f"the snowball method would take <strong>{snowball.get('months_to_payoff')} months</strong>, "
            f"paying <strong>{format_money(snowball.get('total_interest'))}</strong> in interest.</p>"
        )

    debt_recs = debt.get("recommendations") or []
    if debt_recs:
        items = []
        for r in debt_recs:
            title = _esc(r.get("title"))
            description = _esc(r.get("description"))
            impact = r.get("impact")
            impact_clause = f" <em>{_esc(impact)}</em>" if impact else ""
            items.append(f"<li><strong>{title}</strong>: {description}{impact_clause}</li>")
        debt_block.append("<ul>" + "".join(items) + "</ul>")

    if debt_block:
        sections.append("<h3>Debt payoff plan</h3>" + "".join(debt_block))

    return "".join(sections)


def render_final(bundle: dict, approved: bool = True) -> dict[str, str]:
    """Returns {"confirmation_html": ..., "recommendations_html": ...}.

    When `approved` is False (the critic never approved within
    MAX_CRITIQUE_ROUNDS), prepends a calm caveat to the confirmation section
    rather than withholding a completed analysis run's output entirely.
    """
    confirmation = render_confirmation(bundle)
    if not approved:
        confirmation = (
            "<p><em>This reflects the most recent draft; it didn't complete a "
            "final consistency check.</em></p>" + confirmation
        )
    return {
        "confirmation_html": confirmation,
        "recommendations_html": render_recommendations(bundle),
    }
```

- [ ] **Step 4: Run the test file to verify it passes**

Run: `uv run pytest tests/unit/test_presenter.py -v`
Expected: PASS — all 13 tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/presenter.py tests/unit/test_presenter.py
git commit -m "Add deterministic presenter.py to render the final bundle as prose HTML"
```

---

### Task 2: `frontend/main.py` — JSON API rewrite

**Files:**
- Rewrite: `frontend/main.py` (replace the entire current file, `frontend/main.py:1-275`)
- Test: `tests/unit/test_frontend_api.py` (new)
- Test: `tests/smoke/test_frontend_api_smoke.py` (new)
- Modify: `.agents-cli-spec.md:65-67` (update the one-line frontend description)

**Interfaces:**
- Consumes (from Task 1): `frontend.presenter.assemble_final_bundle(state: dict) -> dict`, `frontend.presenter.render_final(bundle: dict, approved: bool = True) -> dict[str, str]`
- Consumes (existing, unchanged): `app.agent.app` (the ADK `App` instance), `google.adk.runners.Runner`, `google.adk.sessions.InMemorySessionService`
- Produces (used by Task 3): three routes — `GET /` (serves `frontend/static/index.html`), `POST /api/analyze` (multipart form: `message: str`, `documents: list[UploadFile]`), `POST /api/resume` (JSON body: `{session_id, answer, skip_remaining}`), `POST /api/resume-security` (JSON body: `{session_id, proceed}`) — all three POST routes return one of the three JSON shapes in Global Constraints. Also mounts `/static` for `frontend/static/*`.

- [ ] **Step 1: Write the failing deterministic API test**

Create `tests/unit/test_frontend_api.py`:

```python
"""Unit tests for frontend/main.py's non-LLM-dependent routes. Anything that
runs the actual Workflow (a real Gemini call) belongs in
tests/smoke/test_frontend_api_smoke.py instead, per this project's testing
conventions (AGENTS.md).
"""

from starlette.testclient import TestClient

from frontend.main import app

client = TestClient(app)


def test_index_serves_the_static_shell():
    response = client.get("/")
    assert response.status_code == 200
    assert "How can I help you today?" in response.text


def test_resume_without_a_pending_session_returns_409():
    response = client.post("/api/resume", json={"session_id": "nonexistent", "answer": "hi"})
    assert response.status_code == 409
    assert response.json()["type"] == "error"


def test_resume_security_without_a_pending_session_returns_409():
    response = client.post("/api/resume-security", json={"session_id": "nonexistent", "proceed": True})
    assert response.status_code == 409
    assert response.json()["type"] == "error"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_frontend_api.py -v`
Expected: FAIL — `frontend/main.py` doesn't yet serve `frontend/static/index.html` (doesn't exist until Task 3) or return 409s (current file returns HTML with a 200).

- [ ] **Step 3: Rewrite `frontend/main.py`**

```python
"""FastAPI backend for the modern-chat-style financial-coach-agent frontend.

Serves a static SPA shell (frontend/static/) and a small JSON API that
drives it. Runs the agent locally via the ADK Runner (in-process — no
separate `agents-cli playground` server required). See
docs/superpowers/specs/2026-07-05-modern-chat-style-frontend-design.md for
the full design this implements.

Run with: `uv run uvicorn frontend.main:app --port 8080`
"""

import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before importing app.agent, which builds Gemini clients

from fastapi import FastAPI, File, Form, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import app as adk_app  # noqa: E402
from frontend.presenter import assemble_final_bundle, render_final  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

fastapi_app = FastAPI(title="financial-coach-agent frontend")
fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_REQUEST_INPUT_FUNCTION_CALL_NAME = "adk_request_input"

_session_service = InMemorySessionService()
_runner = Runner(app=adk_app, session_service=_session_service)

# session_id -> interrupt_id, for sessions currently paused waiting on a
# clarifying or security answer. Local dev only — in-memory is fine.
_pending: dict[str, str] = {}


def _find_pending_interrupt(events: list) -> tuple[str, str] | None:
    """Returns (interrupt_id, message) for the paused interrupt, if any."""
    for event in reversed(events):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            fc = part.function_call
            if fc and fc.name == _REQUEST_INPUT_FUNCTION_CALL_NAME:
                return fc.id, (fc.args or {}).get("message", "")
    return None


async def _run_turn(session_id: str, new_message: types.Content) -> dict:
    events = [
        event
        async for event in _runner.run_async(
            user_id="web_user",
            session_id=session_id,
            new_message=new_message,
        )
    ]

    pending = _find_pending_interrupt(events)
    if pending is not None:
        interrupt_id, message = pending
        _pending[session_id] = interrupt_id
        kind = "security" if interrupt_id == "security_confirm" else "question"
        return {"type": kind, "session_id": session_id, "message": message}

    _pending.pop(session_id, None)
    session = await _session_service.get_session(
        app_name="app", user_id="web_user", session_id=session_id
    )
    bundle = assemble_final_bundle(session.state)
    approved = bool((session.state.get("critic_verdict") or {}).get("approved", False))
    rendered = render_final(bundle, approved=approved)
    return {"type": "final", "session_id": session_id, **rendered}


@fastapi_app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@fastapi_app.post("/api/analyze")
async def analyze(
    message: str = Form(""),
    documents: list[UploadFile] = File(default=[]),
) -> JSONResponse:
    session_id = str(uuid.uuid4())
    await _session_service.create_session(app_name="app", user_id="web_user", session_id=session_id)

    parts = []
    for doc in documents:
        if not doc.filename:
            continue
        data = await doc.read()
        if data:
            parts.append(types.Part.from_bytes(data=data, mime_type="application/pdf"))
    if message.strip():
        parts.append(types.Part.from_text(text=message))
    if not parts:
        parts.append(types.Part.from_text(text=""))

    new_message = types.Content(role="user", parts=parts)
    return JSONResponse(await _run_turn(session_id, new_message))


@fastapi_app.post("/api/resume")
async def resume(payload: dict) -> JSONResponse:
    session_id = payload["session_id"]
    interrupt_id = _pending.get(session_id)
    if interrupt_id is None:
        return JSONResponse(
            {"type": "error", "message": "No pending question for this session."},
            status_code=409,
        )

    response_content = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name=_REQUEST_INPUT_FUNCTION_CALL_NAME,
                    response={
                        "answer": payload.get("answer", ""),
                        "skip_remaining": bool(payload.get("skip_remaining", False)),
                    },
                )
            )
        ],
    )
    return JSONResponse(await _run_turn(session_id, response_content))


@fastapi_app.post("/api/resume-security")
async def resume_security(payload: dict) -> JSONResponse:
    session_id = payload["session_id"]
    interrupt_id = _pending.get(session_id)
    if interrupt_id is None:
        return JSONResponse(
            {"type": "error", "message": "No pending question for this session."},
            status_code=409,
        )

    response_content = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name=_REQUEST_INPUT_FUNCTION_CALL_NAME,
                    response={"proceed": bool(payload.get("proceed", False))},
                )
            )
        ],
    )
    return JSONResponse(await _run_turn(session_id, response_content))


app = fastapi_app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
```

Note: `test_index_serves_the_static_shell` (Step 1) will still fail after this step alone, since `frontend/static/index.html` doesn't exist until Task 3 — `FileResponse` will 404. That's expected; Step 4 below only asserts the 409 tests pass yet. The full green run for all three tests happens at the end of Task 3.

- [ ] **Step 4: Run the two 409 tests to verify they now pass**

Run: `uv run pytest tests/unit/test_frontend_api.py::test_resume_without_a_pending_session_returns_409 tests/unit/test_frontend_api.py::test_resume_security_without_a_pending_session_returns_409 -v`
Expected: PASS — both 409 tests green. (`test_index_serves_the_static_shell` still fails until Task 3 creates `frontend/static/index.html` — leave it red for now.)

- [ ] **Step 5: Write the smoke test**

Create `tests/smoke/test_frontend_api_smoke.py`:

```python
"""Runnable smoke test (NOT pytest) for the frontend's JSON API
(frontend/main.py), exercising a real Gemini call end to end. Confirms
/api/analyze eventually returns a "final" response with both HTML
sections populated, after resuming past any intake-loop clarifying
questions with skip_remaining=True (mirrors the pattern already used in
tests/smoke/test_transaction_fetcher_typed_text_smoke.py).

Run with: uv run python tests/smoke/test_frontend_api_smoke.py
"""

from dotenv import load_dotenv

load_dotenv()

from starlette.testclient import TestClient  # noqa: E402

from frontend.main import app  # noqa: E402

MESSAGE = (
    "My monthly income is 5000, I have 2 dependants. My expenses are: Housing 1500, Food 600, "
    "Transportation 300, Utilities 200, Entertainment 100, Healthcare 80, Personal 120, Other 100. "
    "I have one debt: Credit Card, amount 4000, interest rate 22%, minimum payment 100."
)


def main() -> None:
    client = TestClient(app)

    response = client.post("/api/analyze", data={"message": MESSAGE})
    data = response.json()
    assert response.status_code == 200, data

    for _ in range(4):
        if data["type"] == "final":
            break
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

    assert data["type"] == "final", f"expected a final response within the round cap, got: {data}"
    assert "Your Financial Picture" in data["confirmation_html"]
    assert "Recommendations" in data["recommendations_html"]
    assert "{" not in data["confirmation_html"]
    assert "{" not in data["recommendations_html"]
    print("Frontend API smoke assertions passed — final response reached with both sections rendered.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the smoke test**

Run: `uv run python tests/smoke/test_frontend_api_smoke.py`
Expected: `Frontend API smoke assertions passed — final response reached with both sections rendered.`

- [ ] **Step 7: Update the stale architecture line in `.agents-cli-spec.md`**

In `.agents-cli-spec.md`, replace the existing line (currently at `.agents-cli-spec.md:65-67`):

```
- Frontend: `frontend/main.py` — local FastAPI text-entry form, runs the agent in-process via
  `Runner(app=app, ...)`; persists `session_id` across requests and renders/resumes the intake
  loop's clarifying questions via a `function_response` form post.
```

with:

```
- Frontend: `frontend/main.py` — local FastAPI JSON API (`/api/analyze`, `/api/resume`,
  `/api/resume-security`), runs the agent in-process via `Runner(app=app, ...)`. Serves a static
  vanilla-JS SPA shell (`frontend/static/`) that renders a modern-chat-style chat transcript with no
  page reloads, and resumes the intake/security interrupts via `function_response` posts.
  `frontend/presenter.py` deterministically renders the final analysis bundle as prose HTML — no
  LLM call, no JSON shown to the user. See
  `docs/superpowers/specs/2026-07-05-modern-chat-style-frontend-design.md` for the full design.
```

- [ ] **Step 8: Commit**

```bash
git add frontend/main.py tests/unit/test_frontend_api.py tests/smoke/test_frontend_api_smoke.py .agents-cli-spec.md
git commit -m "Rewrite frontend/main.py as a JSON API for the SPA-lite chat frontend"
```

---

### Task 3: Static SPA shell — `frontend/static/{index.html,style.css,app.js}`

**Files:**
- Create: `frontend/static/index.html`
- Create: `frontend/static/style.css`
- Create: `frontend/static/app.js`

**Interfaces:**
- Consumes (from Task 2): `GET /`, `POST /api/analyze` (multipart: `message`, `documents[]`), `POST /api/resume` (JSON: `{session_id, answer, skip_remaining}`), `POST /api/resume-security` (JSON: `{session_id, proceed}`), and the three response shapes from Global Constraints.
- Produces: nothing consumed by a later task — this is the final rendering layer.

- [ ] **Step 1: Create `frontend/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Financial Coach Agent</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div id="empty-state" class="empty-state">
    <h1>How can I help you today?</h1>
    <p class="subtitle">I'll look at your income, spending, debts, and savings goals and put
      together a full picture with a debt-payoff plan and savings strategy — type it in, or
      upload statements below.</p>
    <div class="example-chips">
      <button type="button" class="chip">I make $5,000/month, rent is $1,500, and I have a $4,000 credit card at 22% interest.</button>
      <button type="button" class="chip">My income is $6,200/month. I have a car loan at 0.99% and a student loan at 5.99%.</button>
      <button type="button" class="chip">I don't have a budget yet — here's my last month of spending by category.</button>
      <button type="button" class="chip">Upload my bank statement and credit card statements for a full picture.</button>
    </div>
  </div>

  <div id="transcript" class="transcript"></div>

  <div id="file-chips" class="file-chips"></div>

  <form id="composer" class="composer">
    <button type="button" id="upload-btn" class="icon-button" title="Upload files" aria-label="Upload files">📎</button>
    <input type="file" id="file-input" accept="application/pdf" multiple hidden>
    <textarea id="message-input" placeholder="Describe your income, expenses, and any debts..." rows="1"></textarea>
    <button type="submit" id="send-btn" class="icon-button send-button" title="Send" aria-label="Send" disabled>➤</button>
  </form>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `frontend/static/style.css`**

```css
:root {
  --bg: #faf9f7;
  --text: #1a1a1a;
  --muted: #6b6b6b;
  --border: #e0ddd6;
  --user-bg: #f0eee8;
  --accent: #b45f34;
}

* { box-sizing: border-box; }

html, body { height: 100%; }

body {
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--bg);
  color: var(--text);
  font-family: ui-sans-serif, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 16px;
  line-height: 1.6;
}

/* Before the first message: center the empty-state block and the composer
   together as one group, so the input box sits directly below the heading
   — not pinned to the literal bottom of the viewport. */
body:not(.started) {
  justify-content: center;
}

/* After the first message: pin the composer to the bottom and let only the
   transcript scroll, by bounding body to exactly the viewport height. */
body.started {
  justify-content: flex-start;
  overflow: hidden;
}

.empty-state {
  width: 100%;
  max-width: 48rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 24px;
}

.empty-state h1 {
  font-size: 1.75rem;
  font-weight: 500;
  margin: 0 0 12px;
}

.empty-state .subtitle {
  color: var(--muted);
  font-size: 0.95rem;
  max-width: 34rem;
  margin: 0 0 24px;
}

.example-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.chip {
  border: 1px solid var(--border);
  background: white;
  border-radius: 999px;
  padding: 8px 16px;
  font-size: 0.85rem;
  cursor: pointer;
  color: var(--text);
}

.chip:hover {
  background: var(--user-bg);
}

.transcript {
  display: none;
  width: 100%;
  max-width: 48rem;
  padding: 24px;
}

body.started .empty-state { display: none; }
body.started .transcript {
  display: block;
  flex: 1;
  overflow-y: auto;
}

.turn { margin-bottom: 24px; }

.turn.user { display: flex; justify-content: flex-end; }

.turn.user .bubble {
  background: var(--user-bg);
  border-radius: 1rem;
  padding: 12px 16px;
  display: inline-block;
  max-width: 90%;
}

.turn.assistant { padding: 0 4px; }

.turn.assistant h2 { font-size: 1.15rem; margin: 20px 0 8px; }
.turn.assistant h3 { font-size: 1rem; margin: 16px 0 6px; }
.turn.assistant ul, .turn.assistant ol { margin: 4px 0; padding-left: 1.4rem; }
.turn.assistant li { margin: 4px 0; }

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 0.8rem;
  margin: 0 6px 6px 0;
  background: white;
}

.file-chips {
  width: 100%;
  max-width: 48rem;
  padding: 0 24px;
  flex-shrink: 0;
}

.composer {
  width: 100%;
  max-width: 48rem;
  flex-shrink: 0;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 1.25rem;
  background: white;
  padding: 10px 12px;
  margin: 0 24px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.composer:focus-within {
  box-shadow: 0 0 0 2px var(--accent);
}

#message-input {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  font: inherit;
  max-height: 200px;
  background: transparent;
}

.icon-button {
  border: none;
  background: transparent;
  font-size: 1.2rem;
  cursor: pointer;
  border-radius: 999px;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
}

.icon-button:disabled {
  opacity: 0.35;
  cursor: default;
}

.send-button {
  background: var(--accent);
  color: white;
}

.send-button:disabled {
  background: var(--border);
  color: var(--muted);
}

.inline-reply {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 32rem;
}

.inline-reply textarea {
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  padding: 8px 12px;
  font: inherit;
  resize: vertical;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.button {
  border: 1px solid var(--border);
  background: white;
  border-radius: 999px;
  padding: 6px 16px;
  cursor: pointer;
  font: inherit;
}

.button.primary {
  background: var(--accent);
  color: white;
  border-color: var(--accent);
}
```

- [ ] **Step 3: Create `frontend/static/app.js`**

```javascript
(() => {
  const body = document.body;
  const transcript = document.getElementById("transcript");
  const composer = document.getElementById("composer");
  const messageInput = document.getElementById("message-input");
  const sendBtn = document.getElementById("send-btn");
  const uploadBtn = document.getElementById("upload-btn");
  const fileInput = document.getElementById("file-input");
  const fileChipsEl = document.getElementById("file-chips");
  const chips = document.querySelectorAll(".chip");

  let sessionId = null;
  let selectedFiles = [];

  function updateSendState() {
    sendBtn.disabled = messageInput.value.trim() === "" && selectedFiles.length === 0;
  }

  function autoGrow() {
    messageInput.style.height = "auto";
    messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + "px";
  }

  function renderFileChips() {
    fileChipsEl.innerHTML = "";
    selectedFiles.forEach((file, index) => {
      const chip = document.createElement("span");
      chip.className = "file-chip";
      chip.textContent = file.name + " ";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.style.border = "none";
      remove.style.background = "transparent";
      remove.style.cursor = "pointer";
      remove.addEventListener("click", () => {
        selectedFiles.splice(index, 1);
        renderFileChips();
        updateSendState();
      });
      chip.appendChild(remove);
      fileChipsEl.appendChild(chip);
    });
  }

  function startConversation() {
    body.classList.add("started");
  }

  function addUserTurn(text, files) {
    const turn = document.createElement("div");
    turn.className = "turn user";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (text) {
      const p = document.createElement("div");
      p.textContent = text;
      bubble.appendChild(p);
    }
    files.forEach((file) => {
      const chip = document.createElement("span");
      chip.className = "file-chip";
      chip.textContent = "📄 " + file.name;
      bubble.appendChild(chip);
    });
    turn.appendChild(bubble);
    transcript.appendChild(turn);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function addAssistantTurn() {
    const turn = document.createElement("div");
    turn.className = "turn assistant";
    transcript.appendChild(turn);
    transcript.scrollTop = transcript.scrollHeight;
    return turn;
  }

  function renderQuestionTurn(message) {
    const turn = addAssistantTurn();
    const p = document.createElement("p");
    p.textContent = message;
    turn.appendChild(p);

    const reply = document.createElement("div");
    reply.className = "inline-reply";
    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.placeholder = "Your answer...";
    const actions = document.createElement("div");
    actions.className = "actions";
    const skipLabel = document.createElement("label");
    const skipCheckbox = document.createElement("input");
    skipCheckbox.type = "checkbox";
    skipLabel.appendChild(skipCheckbox);
    skipLabel.appendChild(document.createTextNode(" Skip further questions"));
    const replyBtn = document.createElement("button");
    replyBtn.type = "button";
    replyBtn.className = "button primary";
    replyBtn.textContent = "Reply";
    replyBtn.addEventListener("click", async () => {
      const answer = textarea.value;
      addUserTurn(answer || "(skip remaining questions)", []);
      reply.remove();
      await sendResume({ session_id: sessionId, answer, skip_remaining: skipCheckbox.checked });
    });
    actions.appendChild(skipLabel);
    actions.appendChild(replyBtn);
    reply.appendChild(textarea);
    reply.appendChild(actions);
    turn.appendChild(reply);
  }

  function renderSecurityTurn(message) {
    const turn = addAssistantTurn();
    const p = document.createElement("p");
    p.textContent = message;
    turn.appendChild(p);

    const actions = document.createElement("div");
    actions.className = "actions";
    const continueBtn = document.createElement("button");
    continueBtn.type = "button";
    continueBtn.className = "button primary";
    continueBtn.textContent = "Continue";
    const stopBtn = document.createElement("button");
    stopBtn.type = "button";
    stopBtn.className = "button";
    stopBtn.textContent = "Stop here";

    async function choose(proceed) {
      addUserTurn(proceed ? "Continue" : "Stop here", []);
      actions.remove();
      await sendResumeSecurity({ session_id: sessionId, proceed });
    }

    continueBtn.addEventListener("click", () => choose(true));
    stopBtn.addEventListener("click", () => choose(false));
    actions.appendChild(continueBtn);
    actions.appendChild(stopBtn);
    turn.appendChild(actions);
  }

  function renderFinalTurn(confirmationHtml, recommendationsHtml) {
    const turn = addAssistantTurn();
    turn.innerHTML = confirmationHtml + recommendationsHtml;
    sessionId = null;
  }

  function handleResponse(data) {
    if (data.type === "question") {
      renderQuestionTurn(data.message);
    } else if (data.type === "security") {
      renderSecurityTurn(data.message);
    } else if (data.type === "final") {
      renderFinalTurn(data.confirmation_html, data.recommendations_html);
    } else {
      renderQuestionTurn(data.message || "Something went wrong — please try again.");
    }
  }

  async function sendResume(payload) {
    const response = await fetch("/api/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    handleResponse(await response.json());
  }

  async function sendResumeSecurity(payload) {
    const response = await fetch("/api/resume-security", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    handleResponse(await response.json());
  }

  async function sendAnalyze(text, files) {
    const formData = new FormData();
    formData.append("message", text);
    files.forEach((file) => formData.append("documents", file));
    const response = await fetch("/api/analyze", { method: "POST", body: formData });
    const data = await response.json();
    sessionId = data.session_id;
    handleResponse(data);
  }

  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = messageInput.value.trim();
    if (!text && selectedFiles.length === 0) return;

    startConversation();
    addUserTurn(text, selectedFiles);
    sendBtn.disabled = true;

    const files = selectedFiles;
    selectedFiles = [];
    renderFileChips();
    messageInput.value = "";
    autoGrow();
    updateSendState();

    await sendAnalyze(text, files);
  });

  messageInput.addEventListener("input", () => {
    autoGrow();
    updateSendState();
  });

  uploadBtn.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", () => {
    selectedFiles = selectedFiles.concat(Array.from(fileInput.files));
    fileInput.value = "";
    renderFileChips();
    updateSendState();
  });

  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      messageInput.value = chip.textContent;
      autoGrow();
      updateSendState();
      messageInput.focus();
    });
  });
})();
```

- [ ] **Step 4: Run the full `test_frontend_api.py` file to verify all three tests now pass**

Run: `uv run pytest tests/unit/test_frontend_api.py -v`
Expected: PASS — all 3 tests green, including `test_index_serves_the_static_shell` (now that `frontend/static/index.html` exists).

- [ ] **Step 5: Commit**

```bash
git add frontend/static/index.html frontend/static/style.css frontend/static/app.js
git commit -m "Add modern-chat-style SPA shell (HTML/CSS/JS) for the frontend"
```

---

### Task 4: Full-suite verification and manual browser QA

**Files:** none created or modified — verification only.

**Interfaces:** none — this task runs the full test suite and a manual pass; it produces no new interface.

- [ ] **Step 1: Run the full automated test suite**

Run: `uv run pytest tests/unit/ -v`
Expected: PASS — every test in `tests/unit/` green, including Tasks 1-3's new tests and the pre-existing `test_security_checkpoint.py` and `test_dummy.py` (confirms nothing in the rewrite broke existing coverage).

- [ ] **Step 2: Run every smoke test that touches the frontend or the pipeline it depends on**

Run: `uv run python tests/smoke/test_frontend_api_smoke.py`
Run: `uv run python tests/smoke/test_transaction_fetcher_typed_text_smoke.py`
Run: `uv run python tests/smoke/test_security_escalation_smoke.py`
Expected: PASS for all three — confirms the rewritten `frontend/main.py` didn't regress `security_checkpoint`/`intake_loop`/`TransactionFetcherAgent` behavior (unchanged by this plan, but the API layer calling into them changed).

- [ ] **Step 3: Manual browser verification**

Start the dev server:

```bash
uv run uvicorn frontend.main:app --port 8080
```

In a browser at `http://127.0.0.1:8080/`, verify each of these (per this project's convention that UI changes are checked in a real browser before being called done, not just via automated tests):
1. **Empty state**: "How can I help you today?" heading, subtitle, and example chips are visible; clicking a chip fills the textbox without submitting.
2. **Golden path**: type a complete message (income, expenses, one debt), submit — the transcript shows the user's message in a shaded bubble, the input box pins to the bottom, and eventually a "Your Financial Picture" / "Recommendations" response renders as prose with bolded numbers, bullets, and no visible JSON or curly braces.
3. **File upload path**: click the paperclip, select one of `tests/fixtures/documents/*.pdf`, confirm it appears as a removable chip before sending, then submit and confirm it reaches a final response.
4. **Intake question round**: submit a deliberately vague message (e.g. "I have some income and spend on stuff") and confirm the clarifying question renders as a plain assistant turn with an inline reply box, not a page reload.
5. **Security check**: submit a message containing an injection phrase from `app/agent.py`'s `_INJECTION_PHRASES` (e.g. "ignore previous instructions") and confirm the calm "Continue" / "Stop here" turn renders inline; verify both button choices work.

- [ ] **Step 4: Stop the dev server**

Press `Ctrl+C` in the terminal running `uvicorn`.

- [ ] **Step 5: Final commit (only if Step 3 surfaced fixes)**

If manual verification in Step 3 required any code changes, commit them now with a message describing what was fixed. If no changes were needed, skip this step — Tasks 1-3's commits already cover the complete implementation.
