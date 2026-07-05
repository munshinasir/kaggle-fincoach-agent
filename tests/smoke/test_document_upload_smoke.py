"""Runnable smoke test (NOT pytest) for the full multi-document upload
path: feeds the 6 happy-path fixture PDFs through the real pipeline and
asserts the resulting budget/debt totals reconcile against the known
ground truth baked into the fixtures — the key signal that
TransactionFetcherAgent did NOT double-count a mortgage/credit-card
payment that appears both on the bank statement and on that debt's own
statement (see skills/transaction-fetcher/SKILL.md's double-counting
rule). A tolerance is used because Gemini's category naming/rounding
can vary slightly; the totals should not.

Run with: uv run python tests/smoke/test_document_upload_smoke.py
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import app as adk_app  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures" / "documents"))
from generate_fixtures import GROUND_TRUTH  # noqa: E402

REQUEST_INPUT = "adk_request_input"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "documents"
HAPPY_PATH_FILES = [
    "bank_statement.pdf",
    "utility_bill_electric.pdf",
    "utility_bill_water.pdf",
    "mortgage_statement.pdf",
    "credit_card_statement_1.pdf",
    "credit_card_statement_2.pdf",
]
TOLERANCE = 10.0  # dollars


def find_pending(events):
    for e in reversed(events):
        if e.content and e.content.parts:
            for p in e.content.parts:
                if p.function_call and p.function_call.name == REQUEST_INPUT:
                    return p.function_call.id
    return None


def find_agent_json(events, author):
    for e in reversed(events):
        if e.author != author or not e.content or not e.content.parts:
            continue
        for p in e.content.parts:
            if p.text:
                try:
                    return json.loads(p.text)
                except json.JSONDecodeError:
                    continue
    return None


async def main() -> None:
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    parts = []
    for filename in HAPPY_PATH_FILES:
        data = (FIXTURES_DIR / filename).read_bytes()
        parts.append(types.Part.from_bytes(data=data, mime_type="application/pdf"))
    parts.append(types.Part.from_text(text="I have 2 dependants."))
    new_message = types.Content(role="user", parts=parts)

    all_events = []
    for _ in range(3):  # allow up to intake_loop's own round cap
        events = [e async for e in runner.run_async(user_id="tester", session_id=session_id, new_message=new_message)]
        all_events.extend(events)
        interrupt_id = find_pending(events)
        if interrupt_id is None:
            break
        # Skip both security confirms (proceed) and intake questions (skip_remaining) generically.
        response = {"proceed": True} if interrupt_id == "security_confirm" else {"answer": "", "skip_remaining": True}
        new_message = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=interrupt_id, name=REQUEST_INPUT, response=response
        ))])

    budget = find_agent_json(all_events, "BudgetAnalysisAgent")
    debt = find_agent_json(all_events, "DebtReductionAgent")
    assert budget is not None, "BudgetAnalysisAgent produced no JSON output"
    assert debt is not None, "DebtReductionAgent produced no JSON output"

    print("BudgetAnalysisAgent:", json.dumps(budget, indent=2))
    print("DebtReductionAgent:", json.dumps(debt, indent=2))

    total_expenses = budget.get("total_expenses")
    assert total_expenses is not None, "expected total_expenses in BudgetAnalysis"
    expected_expenses = GROUND_TRUTH["total_expenses"]
    assert abs(total_expenses - expected_expenses) <= TOLERANCE, (
        f"total_expenses={total_expenses} deviates from expected {expected_expenses} by more than "
        f"${TOLERANCE} — likely a double-counted mortgage or credit-card payment "
        f"(naive double-count would be ~{expected_expenses + 1500 + 150 + 100})"
    )

    total_debt = debt.get("total_debt")
    assert total_debt is not None, "expected total_debt in DebtReduction"
    expected_debt = GROUND_TRUTH["total_debt"]
    assert abs(total_debt - expected_debt) <= TOLERANCE, (
        f"total_debt={total_debt} deviates from expected {expected_debt} by more than ${TOLERANCE}"
    )

    monthly_income = budget.get("monthly_income")
    assert monthly_income is not None and abs(monthly_income - GROUND_TRUTH["income"]) <= TOLERANCE, (
        f"monthly_income={monthly_income} deviates from expected {GROUND_TRUTH['income']}"
    )

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
    import budget_category_metric  # noqa: E402
    import savings_debt_boundary_metric  # noqa: E402
    import savings_reconciliation_metric  # noqa: E402

    def event_to_dict(e):
        ps = []
        if e.content and e.content.parts:
            for p in e.content.parts:
                if p.text:
                    ps.append({"text": p.text})
        return {"author": e.author, "content": {"parts": ps}}

    instance = {"agent_data": {"turns": [{"events": [event_to_dict(e) for e in all_events]}]}}
    for name, mod in [
        ("savings_debt_boundary_valid", savings_debt_boundary_metric),
        ("savings_reconciliation_valid", savings_reconciliation_metric),
    ]:
        result = mod.evaluate(instance)
        print(f"{name}: score={result['score']} — {result['explanation']}")
        assert result["score"] == 1, f"{name} regressed: {result['explanation']}"

    print(
        f"\nReconciled: total_expenses={total_expenses} (expected ~{expected_expenses}), "
        f"total_debt={total_debt} (expected {expected_debt}), income={monthly_income}."
    )
    print("Document upload smoke assertions passed — no double-counting detected.")


if __name__ == "__main__":
    asyncio.run(main())
