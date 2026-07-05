"""Regression check: savings-strategy's allocations must reconcile against total_surplus.

Found via eval (custom_response_quality flagged it): an earlier version allocated
recommendations from the full total_surplus without first reserving debt minimum
payments, over-allocating by exactly the debt's minimum payment. This asserts:

    sum(allocation-type recommendations[].amount) + sum(debt minimum payments)
        + available_surplus_after_savings == total_surplus (within a small tolerance)

`spending_cut`-type recommendations are excluded from the sum (added in v2 Phase 3,
alongside SavingsRecommendation.type): a cut frees up new money from an existing
expense that isn't part of total_surplus yet, so it neither consumes from nor adds
to this identity — see skills/savings-strategy/SKILL.md step 5/11 and skills/critic/SKILL.md.
"""

import json
import re

_TOLERANCE = 1.0  # dollars — allow minor rounding, not a systemic miscount


def _find_agent_json(instance, agent_name):
    turns = (instance.get("agent_data") or {}).get("turns", [])
    for turn in turns:
        for event in turn.get("events", []):
            if event.get("author") != agent_name:
                continue
            for part in event.get("content", {}).get("parts", []):
                text = part.get("text")
                if not text:
                    continue
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    match = re.search(r"\{.*\}", text, re.DOTALL)
                    if match:
                        try:
                            return json.loads(match.group(0))
                        except json.JSONDecodeError:
                            continue
    return None


def evaluate(instance):
    budget = _find_agent_json(instance, "BudgetAnalysisAgent")
    savings = _find_agent_json(instance, "SavingsStrategyAgent")
    debt_reduction = _find_agent_json(instance, "DebtReductionAgent")
    if budget is None or savings is None:
        return {"score": 0, "explanation": "BudgetAnalysisAgent or SavingsStrategyAgent output not found in trace."}

    total_surplus = budget.get("total_surplus")
    if total_surplus is None:
        return {"score": 1, "explanation": "No total_surplus reported (deficit scenario) — reconciliation not applicable."}

    debts = (debt_reduction or {}).get("debts", [])
    min_payments = sum(d.get("min_payment") or 0 for d in debts)

    recommended = sum(
        r.get("amount") or 0
        for r in savings.get("recommendations", [])
        if r.get("type", "allocation") != "spending_cut"
    )
    debt_context = savings.get("debt_context") or {}
    available = debt_context.get("available_surplus_after_savings")
    if available is None:
        return {"score": 0, "explanation": "savings_strategy.debt_context.available_surplus_after_savings is missing."}

    accounted = recommended + min_payments + available
    diff = accounted - total_surplus

    if abs(diff) <= _TOLERANCE:
        return {
            "score": 1,
            "explanation": f"Reconciles: recommendations({recommended}) + debt minimums({min_payments}) + available({available}) = {accounted}, total_surplus={total_surplus}.",
        }
    return {
        "score": 0,
        "explanation": (
            f"Does not reconcile: recommendations({recommended}) + debt minimums({min_payments}) + "
            f"available({available}) = {accounted}, but total_surplus={total_surplus} (diff={diff})."
        ),
    }
