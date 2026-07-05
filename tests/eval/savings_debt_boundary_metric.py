"""Regression check for the Savings/Debt ownership boundary (v2 Phase 1).

Verifies savings-strategy analyzes debt (via debt_context) but never prescribes
a dollar amount toward, or names, a specific debt in its own recommendations —
that decision belongs entirely to debt-reduction. Found via manual testing: an
earlier version had a `debt_context.note` naming "the Student Loan" as the
priority, and a `recommendations` entry titled "Prioritize the Student Loan".

Note: `debt_context.note` is allowed to mention that a debt exists (in a
single-debt scenario there's no other way to state the surplus fact) — what's
checked there is *directive* language ("should be applied toward", "prioritize",
"recommend"), not the mere presence of a debt name. `recommendations[]` is held
to the stricter no-debt-name-at-all standard, since a recommendation naming a
specific debt is a prescription by definition.
"""

import json
import re

_DIRECTIVE_PATTERNS = [
    r"\bshould\b",
    r"\bmust\b",
    r"\bprioriti[sz]e\b",
    r"\brecommend(ed|ation)?\b",
    r"\baggressively\b",
    r"\b(apply|direct|put|allocate)(ed|ing)?\s+(toward|against|to)\b",
    r"\bpay(ing)?\s+(it|this|that)\s+(down|off)\b",
]


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
    savings = _find_agent_json(instance, "SavingsStrategyAgent")
    debt_reduction = _find_agent_json(instance, "DebtReductionAgent")
    if savings is None or debt_reduction is None:
        return {
            "score": 0,
            "explanation": "SavingsStrategyAgent or DebtReductionAgent output not found in trace.",
        }

    debt_context = savings.get("debt_context")
    if not debt_context:
        return {"score": 0, "explanation": "savings_strategy is missing debt_context."}

    required_keys = {"debt_to_income_ratio", "available_surplus_after_savings", "has_emergency_fund", "note"}
    missing_keys = required_keys - debt_context.keys()
    if missing_keys:
        return {"score": 0, "explanation": f"debt_context missing keys: {sorted(missing_keys)}"}

    debt_names = [d.get("name", "") for d in debt_reduction.get("debts", []) if d.get("name")]
    leak_locations = []

    note_text = debt_context.get("note", "")
    for pattern in _DIRECTIVE_PATTERNS:
        if re.search(pattern, note_text, re.IGNORECASE):
            leak_locations.append(f"debt_context.note uses directive language ('{pattern}'): {note_text!r}")
            break

    for rec in savings.get("recommendations", []):
        category = str(rec.get("category", ""))
        rationale = str(rec.get("rationale") or "")
        for name in debt_names:
            if name and (name.lower() in category.lower() or name.lower() in rationale.lower()):
                leak_locations.append(f"recommendations entry '{category}' references '{name}'")

    if leak_locations:
        return {
            "score": 0,
            "explanation": "savings_strategy named a specific debt: " + "; ".join(leak_locations),
        }

    return {
        "score": 1,
        "explanation": "debt_context present with required fields; no specific debt named in savings_strategy output.",
    }
