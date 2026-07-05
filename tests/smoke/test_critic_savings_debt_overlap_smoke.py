"""Runnable smoke test (NOT pytest) for the Critic's new rule 5:
savings-vs-debt investment overlap ("debt wins").

Reproduces the real scenario that prompted the rule: SavingsStrategyAgent
recommends an investment-vehicle allocation while DebtReductionAgent is
still directing that same surplus toward above-threshold debt. Seeds a
deliberately conflicting bundle directly into session state and runs
critique_refine_loop alone (bypassing the full pipeline), matching the
isolated-bundle verification pattern already used for Phase 3's original
critic/refiner checks.

Run with: uv run python tests/smoke/test_critic_savings_debt_overlap_smoke.py
"""

import asyncio
import json
import uuid

from dotenv import load_dotenv

load_dotenv()

from google.adk.apps import App  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import critique_refine_loop  # noqa: E402

# Deliberately conflicting bundle: savings_strategy recommends investing
# $1,055 in an index fund while debt_reduction is still prioritizing debt
# above the 8% threshold with that same surplus. Everything else is
# internally consistent so the only expected fix is removing the overlap.
CONFLICTING_STATE = {
    "budget_analysis": {
        "total_expenses": 2195.0,
        "monthly_income": 5000.0,
        "total_surplus": 2805.0,
        "savings_rate": 0.56,
        "spending_categories": [
            {"category": "Housing", "amount": 1500.0, "percentage": 68.34},
            {"category": "Other", "amount": 695.0, "percentage": 31.66},
        ],
        "savings_categories": [{"category": "Spare Change", "amount": 2805.0, "percentage": 100.0}],
        "spending_analysis": [{"category": "Housing", "analysis": "Housing is the largest expense."}],
        "acknowledgments": ["You have a strong 56% savings rate."],
    },
    "savings_strategy": {
        "emergency_fund": {"recommended_amount": 18000.0, "current_amount": 0.0, "current_status": "Building from zero."},
        "recommendations": [
            {"category": "Emergency Fund", "amount": 1500.0, "rationale": "Build your emergency fund.", "type": "allocation"},
            {
                "category": "Aggressive Growth Index Fund",
                "amount": 1055.0,
                "rationale": "Grow long-term wealth with your remaining surplus.",
                "type": "allocation",
            },
        ],
        "automation_techniques": [],
        "debt_context": {
            "debt_to_income_ratio": 0.05,
            "available_surplus_after_savings": 250.0,
            "has_emergency_fund": False,
            "note": "There is discretionary surplus and two outstanding debts.",
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
                "description": (
                    "Both credit cards carry interest rates (22% and 18%) significantly higher than the "
                    "8% investment threshold. The $1,055 surplus currently allocated to an index fund "
                    "should be redirected to debt repayment first for a guaranteed 18-22% return."
                ),
                "impact": "Reduces debt-free timeline and guarantees a better return than investing would.",
            }
        ],
    },
    "overall_picture": {
        "wins": ["Your savings rate is a strong 56%."],
        "next_steps": [
            {
                "category": "Investing",
                "action": "Set up an automated $1,055/mo transfer to an Aggressive Growth Index Fund.",
                "amount": 1055.0,
                "priority": 2,
            },
            {
                "category": "Debt",
                "action": "Redirect surplus to pay down the Visa card first (avalanche method).",
                "amount": 1055.0,
                "priority": 1,
            },
        ],
    },
}


async def main() -> None:
    session_service = InMemorySessionService()
    app = App(root_agent=critique_refine_loop, name="app")
    runner = Runner(app=app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name="app", user_id="tester", session_id=session_id, state=CONFLICTING_STATE
    )

    new_message = types.Content(role="user", parts=[types.Part.from_text(text="review this bundle")])
    events = [e async for e in runner.run_async(user_id="tester", session_id=session_id, new_message=new_message)]

    for e in events:
        if e.content and e.content.parts:
            for p in e.content.parts:
                if p.text:
                    print(f"--- [{e.author}] ---")
                    print(p.text[:600])
                    print()

    session = await session_service.get_session(app_name="app", user_id="tester", session_id=session_id)
    final_savings = session.state.get("savings_strategy", {})
    final_overall = session.state.get("overall_picture", {})

    savings_categories = {r["category"] for r in final_savings.get("recommendations", [])}
    assert "Aggressive Growth Index Fund" not in savings_categories, (
        f"expected the investment-vehicle recommendation to be removed, but recommendations still "
        f"include it: {final_savings.get('recommendations')}"
    )
    assert "Emergency Fund" in savings_categories, (
        "expected the unrelated Emergency Fund recommendation to survive untouched, but it's gone: "
        f"{final_savings.get('recommendations')}"
    )

    next_step_actions = " ".join(s.get("action", "") for s in final_overall.get("next_steps", []))
    assert "Index Fund" not in next_step_actions, (
        f"expected the matching overall_picture.next_steps entry to be dropped too (knock-on effect), "
        f"but it's still present: {final_overall.get('next_steps')}"
    )
    assert "Visa" in next_step_actions or "avalanche" in next_step_actions.lower(), (
        "expected the debt-side next_steps entry to survive untouched"
    )

    print("Final savings_strategy.recommendations:", json.dumps(final_savings.get("recommendations"), indent=2))
    print("Final overall_picture.next_steps:", json.dumps(final_overall.get("next_steps"), indent=2))
    print("\nSavings-vs-debt overlap smoke assertions passed — debt won, investment recommendation removed.")


if __name__ == "__main__":
    asyncio.run(main())
