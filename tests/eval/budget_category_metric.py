"""Deterministic regression check for BudgetAnalysisAgent's output.

Verifies the fix in skills/budget-analysis/SKILL.md: `spending_categories`
must contain exactly the categories present in the user's input `expenses`
(no invented categories, e.g. a debt-payment line), and `percentage` values
must sum to 100%.
"""

import json
import re

EXPECTED_CATEGORIES = {
    "Housing",
    "Food",
    "Transportation",
    "Utilities",
    "Entertainment",
    "Healthcare",
    "Personal",
    "Other",
}


def _find_agent_json(instance, agent_name):
    """Extract and parse the named agent's final JSON text output from the trace."""
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
    if budget is None:
        return {
            "score": 0,
            "explanation": "BudgetAnalysisAgent output not found or not valid JSON in trace.",
        }

    categories = budget.get("spending_categories", [])
    names = {c.get("category") for c in categories}
    extra = names - EXPECTED_CATEGORIES
    missing = EXPECTED_CATEGORIES - names
    total_pct = sum(c.get("percentage") or 0 for c in categories)
    pct_ok = abs(total_pct - 100) < 0.5

    if not extra and not missing and pct_ok:
        return {
            "score": 1,
            "explanation": f"Categories match input exactly; percentages sum to {total_pct:.2f}%.",
        }

    problems = []
    if extra:
        problems.append(f"invented categories not in input: {sorted(extra)}")
    if missing:
        problems.append(f"missing input categories: {sorted(missing)}")
    if not pct_ok:
        problems.append(f"percentages sum to {total_pct:.2f}%, expected 100%")
    return {"score": 0, "explanation": "; ".join(problems)}
