"""financial-coach-agent: multi-agent budget / savings / debt pipeline.

See AGENTS.md and .agents-cli-spec.md for the full spec.
"""

import sys
from pathlib import Path

from google.adk.agents import Agent, SequentialAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters
from pydantic import BaseModel, Field

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


# --- Sub-agents ---
# TransactionFetcherAgent owns the MCP tool call and stays a plain text-output agent,
# handing its result to the next agent via output_key + shared state. (Note: in the
# installed google-adk 2.3.0, output_schema and tool-calling can actually coexist on
# one Agent — verified via llm_agent.py/_output_schema_processor.py source — so this
# split is now a single-responsibility choice, not a technical requirement.)

transaction_fetcher_agent = Agent(
    name="TransactionFetcherAgent",
    model=_model(),
    description="Fetches sample transactions via MCP when the user wants transaction-based analysis.",
    instruction=(
        "You are a data passthrough step, not an analyst. Never produce prose analysis, tables, "
        "summaries, or recommendations — that is the job of later agents in this pipeline.\n\n"
        "If the user asks you to fetch, import, or analyze their transactions (rather than typing "
        "expenses manually), call get_transactions with their user_id (default to 'default_user' if "
        "none is given) and return ONLY the raw tool result as compact JSON, with no other text.\n\n"
        "If the user already provided manual expense data instead, do not call the tool. Return "
        "ONLY that data restated as compact JSON (income, dependants, expenses, debts) — no "
        "commentary, no analysis, no formatting beyond the JSON itself."
    ),
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

budget_analysis_agent = Agent(
    name="BudgetAnalysisAgent",
    model=_model(),
    description="Analyzes financial data to categorize spending patterns and recommend budget improvements",
    instruction=(
        _load_skill_instruction("budget-analysis")
        + "\n\nTransactions fetched via MCP, if any: {raw_transactions}"
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

root_agent = SequentialAgent(
    name="FinanceCoordinatorAgent",
    description="Coordinates specialized finance agents to provide comprehensive financial advice",
    sub_agents=[
        transaction_fetcher_agent,
        budget_analysis_agent,
        savings_strategy_agent,
        debt_reduction_agent,
        overall_picture_agent,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
