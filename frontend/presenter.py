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
