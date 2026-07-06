"""financial-coach-agent: multi-agent budget / savings / debt pipeline.

See AGENTS.md and .agents-cli-spec.md for the full spec.
"""

import re
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Literal

from google.adk.agents import Agent, BaseAgent, LoopAgent, SequentialAgent
from google.adk.agents.context import Context
from google.adk.agents.invocation_context import InvocationContext
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.workflow import START, Workflow, node
from google.genai import types
from mcp import StdioServerParameters
from pydantic import BaseModel, Field

MAX_INTAKE_ROUNDS = 2
MAX_CRITIQUE_ROUNDS = 3

_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_BANK_ACCOUNT_PATTERN = re.compile(
    r"(?:Account|Acct)\s*(?:No\.?|#|Number)?\s*:?\s*(\d{6,17})", re.IGNORECASE
)

_INJECTION_PHRASES = [
    "ignore previous",
    "ignore rules",
    "bypass rules",
    "override instructions",
    "system prompt",
    "ignore instruction",
    "bypass",
    "ignore policies",
    "recommend buying",
    "ignore compliance",
]


def scrub_pii(text: str) -> tuple[str, list[str]]:
    """Redacts SSNs, credit card numbers, and labeled bank account numbers.

    Order matters: SSNs and account numbers are redacted before the credit
    card pattern runs, since a bare account number could otherwise also
    satisfy the 13-16-digit credit card pattern.
    """
    redacted: list[str] = []
    scrubbed = text

    if _SSN_PATTERN.search(scrubbed):
        scrubbed = _SSN_PATTERN.sub("[REDACTED_SSN]", scrubbed)
        redacted.append("SSN")

    if _BANK_ACCOUNT_PATTERN.search(scrubbed):
        scrubbed = _BANK_ACCOUNT_PATTERN.sub(
            lambda m: m.group(0).replace(m.group(1), "[REDACTED_ACCOUNT]"), scrubbed
        )
        redacted.append("Bank Account")

    if _CREDIT_CARD_PATTERN.search(scrubbed):
        scrubbed = _CREDIT_CARD_PATTERN.sub("[REDACTED_CARD]", scrubbed)
        redacted.append("Credit Card")

    return scrubbed, redacted


def strip_injection_phrases(text: str) -> tuple[str, list[str]]:
    """Finds and removes known prompt-injection phrases, case-insensitively.

    Unlike scrub_pii (which redacts sensitive but legitimate data), a
    matched phrase here is adversarial and is removed outright, replaced
    with `[REMOVED]` so the redaction is visible/auditable rather than
    silently deleted.
    """
    flagged: list[str] = []
    scrubbed = text

    for phrase in _INJECTION_PHRASES:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        if pattern.search(scrubbed):
            scrubbed = pattern.sub("[REMOVED]", scrubbed)
            flagged.append(phrase)

    return scrubbed, flagged

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
MCP_SERVER_SCRIPT = Path(__file__).resolve().parent / "transactions_mcp_server.py"


def _load_skill_instruction(skill_name: str) -> str:
    """Read a Skill's instruction body — the markdown after the YAML frontmatter.

    SKILL.md is the single source of truth for each analysis agent's instructions
    (see AGENTS.md, decision 5) — this keeps the agent code and the Skill docs from
    drifting apart.
    """
    text = (SKILLS_DIR / skill_name / "SKILL.md").read_text()
    _, _, body = text.split("---", 2)
    return body.strip()


def _model() -> Gemini:
    return Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    )


# --- Pydantic output schemas ---


class SpendingCategory(BaseModel):
    category: str = Field(..., description="Expense category name")
    amount: float = Field(..., description="Amount spent in this category")
    percentage: float | None = Field(None, description="Percentage of total spending")


class SpendingAnalysis(BaseModel):
    category: str = Field(..., description="Category being analyzed")
    analysis: str = Field(
        ...,
        description=(
            "Descriptive observation only — e.g. how this category compares to typical "
            "spending ratios and to the user's income share. No action verbs (reduce/cut/"
            "switch), no dollar savings estimate — that belongs to the savings-strategy skill."
        ),
    )


class SavingsCategory(BaseModel):
    category: str = Field(..., description="Savings/surplus category name")
    amount: float = Field(..., description="Amount allocated to this category")
    percentage: float | None = Field(
        None, description="Percentage of total_surplus (not of income or total_expenses)"
    )


class BudgetAnalysis(BaseModel):
    total_expenses: float = Field(..., description="Total monthly expenses")
    monthly_income: float | None = Field(None, description="Monthly income")
    total_surplus: float | None = Field(
        None,
        description="monthly_income minus total_expenses; 0 if expenses meet or exceed income",
    )
    savings_rate: float | None = Field(
        None, description="total_surplus / monthly_income, as a fraction (e.g. 0.2 for 20%)"
    )
    spending_categories: list[SpendingCategory] = Field(
        ..., description="Breakdown of spending by category"
    )
    savings_categories: list[SavingsCategory] = Field(
        default_factory=list,
        description="Breakdown of the surplus (total_surplus) by category; empty if there is no surplus",
    )
    spending_analysis: list[SpendingAnalysis] = Field(
        ..., description="Descriptive observations on notable spending categories — not recommendations"
    )
    acknowledgments: list[str] = Field(
        default_factory=list,
        description="Positive callouts only (e.g. savings_rate >= 20%, a category well under typical ratios) — never mixed with analysis or recommendations",
    )


class EmergencyFund(BaseModel):
    recommended_amount: float = Field(..., description="Recommended emergency fund size")
    current_amount: float | None = Field(None, description="Current emergency fund (if any)")
    current_status: str = Field(..., description="Status assessment of emergency fund")


class SavingsRecommendation(BaseModel):
    category: str = Field(
        ...,
        description=(
            "Either a savings allocation destination (e.g. 'Emergency Fund') or a spending "
            "category to reduce (e.g. 'Eating Out') — this skill owns both kinds of recommendation"
        ),
    )
    amount: float = Field(..., description="Recommended monthly amount — allocated or freed up")
    rationale: str | None = Field(None, description="Explanation for this recommendation")
    type: str = Field(
        ...,
        description=(
            "'allocation' — spends money already in discretionary_surplus (consumptive; counts "
            "against the reconciliation identity). 'spending_cut' — frees up NEW money from an "
            "existing expense category that isn't part of total_surplus/discretionary_surplus yet "
            "(additive/hypothetical; excluded from the reconciliation identity, since the cut "
            "hasn't actually happened in the numbers)."
        ),
    )


class AutomationTechnique(BaseModel):
    name: str = Field(..., description="Name of automation technique")
    description: str = Field(..., description="Details of how to implement")


class DebtContext(BaseModel):
    debt_to_income_ratio: float | None = Field(
        None, description="Total monthly debt payments / monthly_income, as a fraction"
    )
    available_surplus_after_savings: float = Field(
        ..., description="total_surplus minus what this skill allocated to its own recommendations"
    )
    has_emergency_fund: bool | None = Field(
        None, description="None if unknown/unstated — do not assume false without saying so"
    )
    note: str = Field(
        ...,
        description=(
            "Descriptive handoff for debt-reduction — facts only (surplus amount, DTI ratio, "
            "that debt exists), no directive verbs (should/prioritize/apply toward/recommend). "
            "Which debt to focus on and how belongs entirely to debt-reduction."
        ),
    )


class SavingsStrategy(BaseModel):
    emergency_fund: EmergencyFund = Field(..., description="Emergency fund recommendation")
    recommendations: list[SavingsRecommendation] = Field(
        ...,
        description=(
            "Combined, deduplicated recommendations — both savings allocations and "
            "spending-reduction actions derived from the budget analysis. Never names a "
            "specific debt or a dollar amount to direct at one — see debt_context."
        ),
    )
    automation_techniques: list[AutomationTechnique] | None = Field(
        None, description="Automation techniques to help save"
    )
    debt_context: DebtContext = Field(
        ..., description="Analysis handoff for debt-reduction — see DebtContext"
    )


class Debt(BaseModel):
    name: str = Field(..., description="Name of debt")
    amount: float = Field(..., description="Current balance")
    interest_rate: float = Field(..., description="Annual interest rate (%)")
    min_payment: float | None = Field(None, description="Minimum monthly payment")


class PayoffPlan(BaseModel):
    total_interest: float = Field(..., description="Total interest paid")
    months_to_payoff: int = Field(..., description="Months until debt-free")
    monthly_payment: float | None = Field(None, description="Recommended monthly payment")


class PayoffPlans(BaseModel):
    avalanche: PayoffPlan = Field(..., description="Highest interest first method")
    snowball: PayoffPlan = Field(..., description="Smallest balance first method")


class DebtRecommendation(BaseModel):
    title: str = Field(..., description="Title of recommendation")
    description: str = Field(..., description="Details of recommendation")
    impact: str | None = Field(None, description="Expected impact of this action")


class DebtReduction(BaseModel):
    total_debt: float = Field(..., description="Total debt amount")
    debts: list[Debt] = Field(..., description="List of all debts")
    payoff_plans: PayoffPlans = Field(..., description="Debt payoff strategies")
    recommendations: list[DebtRecommendation] | None = Field(
        None, description="Recommendations for debt reduction"
    )


class NextStep(BaseModel):
    category: str = Field(..., description="What this step targets")
    action: str = Field(..., description="The concrete action to take")
    amount: float | None = Field(None, description="Dollar amount involved, if any")
    priority: int = Field(..., description="1 = highest priority, ascending from there")


class OverallPicture(BaseModel):
    wins: list[str] = Field(
        ..., description="Positive callouts pulled from budget_analysis and elsewhere — never empty if any exist upstream"
    )
    next_steps: list[NextStep] = Field(
        ...,
        description=(
            "One merged, prioritized list combining savings_strategy's and debt_reduction's "
            "recommendations — not two lists stapled together"
        ),
    )


class IntakeQnA(BaseModel):
    question: str = Field(..., description="The clarifying question asked in this round")
    answer: str = Field(..., description="The user's answer to that question")


class IntakeAssessment(BaseModel):
    outcome: Literal["ask", "proceed", "conversational", "blocked"] = Field(
        ...,
        description=(
            "'ask' — needs one more clarifying question this round. 'proceed' — nothing "
            "outstanding, ready for analysis. 'conversational' — round 0 only, no financial "
            "content at all (pure greeting/thanks). 'blocked' — income is affirmatively "
            "confirmed zero/absent and no savings/investment amount was ever stated."
        ),
    )
    question: str | None = Field(
        None,
        description="One combined question covering everything outstanding this round — only set when outcome == 'ask'",
    )
    target_fields: list[str] = Field(
        default_factory=list, description="Which fields/categories this question is trying to clarify"
    )
    rationale: str | None = Field(None, description="Why this outcome was chosen")


class IntakeAnswer(BaseModel):
    answer: str = Field("", description="The user's free-text answer")
    skip_remaining: bool = Field(
        False, description="True if the user wants to proceed to analysis without answering further"
    )


class EnrichedIntake(BaseModel):
    original_request: str = Field(..., description="The user's original request, verbatim")
    qna: list[IntakeQnA] = Field(default_factory=list, description="Clarification rounds completed, in order")
    proceeded_without_full_info: bool = Field(
        False, description="True if the intake loop stopped (cap or skip) before all ambiguity was resolved"
    )


class SecurityConfirmation(BaseModel):
    proceed: bool = Field(
        False,
        description="True to continue with the already-scrubbed text; False to stop without running analysis",
    )


class CriticIssue(BaseModel):
    document: str = Field(
        ..., description="Which output has the problem: 'budget_analysis', 'savings_strategy', 'debt_reduction', or 'overall_picture'"
    )
    field_path: str = Field(..., description="Where in that document, e.g. 'spending_categories percentages' or 'recommendations[1].amount'")
    problem: str = Field(..., description="What's wrong, stated concretely")
    suggested_fix: str = Field(..., description="The specific correction to make — precise enough for RefinerAgent to apply without re-deriving the analysis")


class CriticVerdict(BaseModel):
    approved: bool = Field(..., description="True if nothing below needs fixing — the loop stops here")
    issues: list[CriticIssue] = Field(default_factory=list, description="Empty when approved=True")


class RefinedBundle(BaseModel):
    budget_analysis: BudgetAnalysis
    savings_strategy: SavingsStrategy
    debt_reduction: DebtReduction
    overall_picture: OverallPicture


# --- Sub-agents ---
# TransactionFetcherAgent owns the MCP tool call and stays a plain text-output agent,
# handing its result to the next agent via output_key + shared state. (Note: in the
# installed google-adk 2.3.0, output_schema and tool-calling can actually coexist on
# one Agent — verified via llm_agent.py/_output_schema_processor.py source — so this
# split is now a single-responsibility choice, not a technical requirement.)

transaction_fetcher_agent = Agent(
    name="TransactionFetcherAgent",
    model=_model(),
    description="Normalizes typed input, MCP-fetched transactions, or uploaded statement documents into one compact JSON financial picture.",
    instruction=_load_skill_instruction("transaction-fetcher"),
    tools=[
        McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=sys.executable,
                    args=[str(MCP_SERVER_SCRIPT)],
                ),
            ),
            tool_filter=["get_transactions"],
        )
    ],
    output_key="raw_transactions",
)

intake_agent = Agent(
    name="IntakeAgent",
    model=_model(),
    description="Decides whether the user's request needs clarification before analysis, and drafts one combined question if so.",
    instruction=_load_skill_instruction("intake-clarification"),
    output_schema=IntakeAssessment,
)

budget_analysis_agent = Agent(
    name="BudgetAnalysisAgent",
    model=_model(),
    description="Analyzes financial data to categorize spending patterns and recommend budget improvements",
    instruction=(
        _load_skill_instruction("budget-analysis")
        + "\n\nTransactions fetched via MCP, if any: {raw_transactions}"
        + "\n\nIntake clarifications gathered before analysis, if any: {enriched_intake}"
    ),
    output_schema=BudgetAnalysis,
    output_key="budget_analysis",
)

savings_strategy_agent = Agent(
    name="SavingsStrategyAgent",
    model=_model(),
    description="Recommends optimal savings strategies based on income, expenses, and financial goals",
    instruction=(
        _load_skill_instruction("savings-strategy")
        + "\n\nBudget analysis from the previous step: {budget_analysis}"
    ),
    output_schema=SavingsStrategy,
    output_key="savings_strategy",
)

debt_reduction_agent = Agent(
    name="DebtReductionAgent",
    model=_model(),
    description="Creates optimized debt payoff plans to minimize interest paid and time to debt freedom",
    instruction=(
        _load_skill_instruction("debt-reduction")
        + "\n\nBudget analysis: {budget_analysis}\nSavings strategy: {savings_strategy}"
    ),
    output_schema=DebtReduction,
    output_key="debt_reduction",
)

overall_picture_agent = Agent(
    name="OverallPictureAgent",
    model=_model(),
    description="Synthesizes budget, savings, and debt analysis into one consolidated, prioritized picture",
    instruction=(
        _load_skill_instruction("overall-picture")
        + "\n\nBudget analysis: {budget_analysis}\nSavings strategy: {savings_strategy}\nDebt reduction: {debt_reduction}"
    ),
    output_schema=OverallPicture,
    output_key="overall_picture",
)

analysis_pipeline = SequentialAgent(
    name="FinanceCoordinatorAgent",
    description="Coordinates specialized finance agents to provide comprehensive financial advice",
    sub_agents=[
        budget_analysis_agent,
        savings_strategy_agent,
        debt_reduction_agent,
        overall_picture_agent,
    ],
)

critic_agent = Agent(
    name="CriticAgent",
    model=_model(),
    description="Cross-checks the full analysis bundle for math errors, unrealistic recommendations, debt-payment violations, and tone before it's shown to the user.",
    instruction=(
        _load_skill_instruction("critic")
        + "\n\nBudget analysis: {budget_analysis}\nSavings strategy: {savings_strategy}"
        + "\nDebt reduction: {debt_reduction}\nOverall picture: {overall_picture}"
    ),
    output_schema=CriticVerdict,
    output_key="critic_verdict",
)


class _EscalationChecker(BaseAgent):
    """Stops the critique/refine LoopAgent once CriticAgent approves the bundle."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        verdict = ctx.session.state.get("critic_verdict") or {}
        if verdict.get("approved"):
            yield Event(author=self.name, actions=EventActions(escalate=True))
        else:
            yield Event(author=self.name)


escalation_checker = _EscalationChecker(name="EscalationChecker")

refiner_agent = Agent(
    name="RefinerAgent",
    model=_model(),
    description="Applies the critic's specific fixes to the analysis bundle, changing only what was flagged.",
    instruction=(
        _load_skill_instruction("refiner")
        + "\n\nCritic verdict: {critic_verdict}"
        + "\nCurrent budget analysis: {budget_analysis}\nCurrent savings strategy: {savings_strategy}"
        + "\nCurrent debt reduction: {debt_reduction}\nCurrent overall picture: {overall_picture}"
    ),
    output_schema=RefinedBundle,
    output_key="refined_bundle",
)


class _BundleUnpacker(BaseAgent):
    """Redistributes RefinerAgent's RefinedBundle back into the individual state keys.

    Keeps state['budget_analysis'] etc. current for the next loop iteration's
    CriticAgent re-check, and for anything downstream that reads those keys —
    output_key only ever writes the single 'refined_bundle' key, not the four
    underlying ones.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        bundle = ctx.session.state.get("refined_bundle") or {}
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "budget_analysis": bundle.get("budget_analysis"),
                    "savings_strategy": bundle.get("savings_strategy"),
                    "debt_reduction": bundle.get("debt_reduction"),
                    "overall_picture": bundle.get("overall_picture"),
                }
            ),
        )


bundle_unpacker = _BundleUnpacker(name="BundleUnpacker")

critique_refine_loop = LoopAgent(
    name="CritiqueRefineLoop",
    description="Repeatedly critiques the analysis bundle and applies fixes until approved or the round cap is hit.",
    sub_agents=[critic_agent, escalation_checker, refiner_agent, bundle_unpacker],
    max_iterations=MAX_CRITIQUE_ROUNDS,
)


@node(rerun_on_resume=True)
async def intake_loop(ctx: Context, node_input: str) -> AsyncGenerator[Event, None]:
    """Bounded (max 2 rounds) clarification loop, run before analysis_pipeline.

    Batches everything IntakeAgent flags into one combined question per round.
    Routes to "analysis" (the default), "conversational" (round 0, no financial
    content at all), or "blocked" (income confirmed zero/absent with no savings
    ever stated) based on IntakeAgent's outcome. Whenever the loop is about to
    stop asking questions with a just-appended answer — either skip_remaining
    was checked, or the round cap was just exhausted by a normal answer — one
    final assessment call checks specifically for "blocked" before falling
    through, so a just-confirmed no-income-no-savings conclusion can never be
    skipped past either way. Always writes state['enriched_intake'] on the
    "analysis" route — analysis_pipeline's SequentialAgent doesn't consume
    node_input directly, so the handoff goes through state, matching the
    {state_var} convention every other agent in this pipeline already uses.
    """
    original_request = node_input
    qna: list[dict] = list(ctx.state.get("intake_qna") or [])
    round_num = len(qna)
    just_answered = False
    force_stop = False

    interrupt_id = f"intake_round_{round_num}"
    if interrupt_id in ctx.resume_inputs:
        answer = ctx.resume_inputs[interrupt_id]
        pending_question = ctx.state.get("intake_pending_question", "")
        qna = qna + [{"question": pending_question, "answer": answer.get("answer", "")}]
        round_num += 1
        just_answered = True
        force_stop = bool(answer.get("skip_remaining"))

    if not force_stop and round_num < MAX_INTAKE_ROUNDS:
        assessment = await ctx.run_node(
            intake_agent,
            node_input={"original_request": original_request, "qna": qna},
            run_id=f"assess_{round_num}",
        )
        outcome = assessment.get("outcome")
        if outcome == "conversational" and round_num == 0:
            yield Event(output=original_request, route="conversational")
            return
        if outcome == "blocked":
            yield Event(output=original_request, route="blocked")
            return
        if outcome == "ask":
            question = assessment.get("question") or (
                "Could you clarify any vague or missing details in your request?"
            )
            yield Event(state={"intake_qna": qna, "intake_pending_question": question})
            yield RequestInput(
                interrupt_id=f"intake_round_{round_num}",
                message=question,
                response_schema=IntakeAnswer,
            )
            return
        # outcome == "proceed" falls through below
    elif just_answered:
        assessment = await ctx.run_node(
            intake_agent,
            node_input={"original_request": original_request, "qna": qna},
            run_id=f"assess_final_{round_num}",
        )
        if assessment.get("outcome") == "blocked":
            yield Event(output=original_request, route="blocked")
            return

    enriched = EnrichedIntake(
        original_request=original_request,
        qna=[IntakeQnA(**q) for q in qna],
        proceeded_without_full_info=force_stop or (round_num >= MAX_INTAKE_ROUNDS and bool(qna)),
    ).model_dump()
    yield Event(output=enriched, state={"enriched_intake": enriched}, route="analysis")


def halted_node(node_input: str) -> str:
    """Terminal node for the 'halted' route — the run ends here, analysis_pipeline never runs."""
    return node_input


_CONVERSATIONAL_NUDGE = (
    "Happy to chat! I'm best at building out a full financial picture, though — "
    "share your income, expenses, and any debts (typed or as an uploaded statement) "
    "and I'll put together a budget, savings, and debt-payoff plan for you."
)

_NO_INCOME_NO_SAVINGS_BLOCK = (
    "We can't put together a financial plan right now — there's no income or savings "
    "for us to build a strategy around. If that changes (a job, a benefit, or some "
    "savings), come back and we'll take a full look."
)


def conversational_node(node_input: str) -> str:
    """Terminal node for the 'conversational' route — round-0 chit-chat with no financial content."""
    return _CONVERSATIONAL_NUDGE


def no_action_node(node_input: str) -> str:
    """Terminal node for the 'blocked' route — confirmed zero income, no savings ever stated."""
    return _NO_INCOME_NO_SAVINGS_BLOCK


@node(rerun_on_resume=True)
async def security_checkpoint(ctx: Context, node_input: str) -> AsyncGenerator[Event, None]:
    """Scrubs PII and neutralizes prompt-injection attempts before intake_loop ever runs.

    PII scrubbing and injection-phrase removal are unconditional — they
    happen before any HITL interrupt, so the payload is neutralized
    whether or not the user later confirms. The interrupt exists purely
    for transparency and an explicit stop option, not to gate the
    scrubbing itself.
    """
    interrupt_id = "security_confirm"
    if interrupt_id in ctx.resume_inputs:
        answer = ctx.resume_inputs[interrupt_id]
        scrubbed_text = ctx.state.get("security_scrubbed_text", "")
        if answer.get("proceed"):
            yield Event(
                output=scrubbed_text,
                route="clean",
                state={"raw_transactions": scrubbed_text},
            )
        else:
            yield Event(
                output="Stopped at your request after a security check.",
                route="halted",
            )
        return

    scrubbed, redacted_types = scrub_pii(node_input)
    scrubbed, flagged_phrases = strip_injection_phrases(scrubbed)

    if not flagged_phrases:
        yield Event(
            output=scrubbed,
            route="clean",
            state={"security_redacted_types": redacted_types, "raw_transactions": scrubbed},
        )
        return

    message = (
        "Before I continue: I removed something from your input that looked like an "
        "attempt to override these agents' instructions"
        + (f", and redacted {', '.join(redacted_types)}" if redacted_types else "")
        + ". Continue with the cleaned version, or stop here?"
    )
    yield Event(state={"security_scrubbed_text": scrubbed, "security_redacted_types": redacted_types})
    yield RequestInput(
        interrupt_id=interrupt_id,
        message=message,
        response_schema=SecurityConfirmation,
    )


root_agent = Workflow(
    name="FinanceCoachWorkflow",
    description="Coordinates transaction intake, security screening, clarification, and the budget/savings/debt analysis pipeline.",
    edges=[
        (START, transaction_fetcher_agent),
        (transaction_fetcher_agent, security_checkpoint),
        (security_checkpoint, {"clean": intake_loop, "halted": halted_node}),
        (intake_loop, {"analysis": analysis_pipeline, "conversational": conversational_node, "blocked": no_action_node}),
        (analysis_pipeline, critique_refine_loop),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True),
)
