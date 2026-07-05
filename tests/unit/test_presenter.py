"""Unit tests for frontend/presenter.py — pure, deterministic, no LLM calls.
See docs/superpowers/specs/2026-07-05-claude-web-style-frontend-design.md
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
