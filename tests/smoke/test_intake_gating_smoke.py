"""Runnable smoke test (NOT pytest) for the new intake-loop routing added to
gate against pure chit-chat and confirmed-zero-income-with-no-savings input,
exercising real Gemini calls end to end via app.agent.app directly (not
through the frontend). See
docs/superpowers/specs/2026-07-05-intake-conversational-and-no-income-gating-design.md.

The existing golden-path smoke tests (test_transaction_fetcher_typed_text_smoke.py,
test_frontend_api_smoke.py) already cover normal financial input reaching
analysis — this file only covers the two new terminal routes plus the savings
exemption that keeps a genuine case from being wrongly blocked.

Run with: uv run python tests/smoke/test_intake_gating_smoke.py
"""

import asyncio
import uuid

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import _CONVERSATIONAL_NUDGE, _NO_INCOME_NO_SAVINGS_BLOCK  # noqa: E402
from app.agent import app as adk_app  # noqa: E402

REQUEST_INPUT = "adk_request_input"
MAX_ROUNDS = 4  # generous bound: MAX_INTAKE_ROUNDS (2) plus slack for resume overhead


def find_pending(events):
    for e in reversed(events):
        if e.content and e.content.parts:
            for p in e.content.parts:
                if p.function_call and p.function_call.name == REQUEST_INPUT:
                    return p.function_call.id
    return None


def find_terminal(events):
    """Returns (node_name, output) for a plain-function terminal node's own
    event.output, if the run ended at one — same technique frontend/main.py
    uses (event.node_info.name, since plain-function @node output surfaces
    via event.output, not event.content).
    """
    for e in events:
        name = getattr(e.node_info, "name", None)
        if name in {"conversational_node", "no_action_node", "halted_node"} and isinstance(
            e.output, str
        ):
            return name, e.output
    return None


async def run_until_terminal_or_final(runner, session_id, first_message):
    """Drives one session through however many intake rounds it takes,
    answering "" with skip_remaining=True on any question, until either a
    terminal node fires or the run has no more pending interrupts (implying
    it reached analysis_pipeline/critique_refine_loop).
    """
    new_message = first_message
    for _ in range(MAX_ROUNDS):
        events = [
            e
            async for e in runner.run_async(
                user_id="tester", session_id=session_id, new_message=new_message
            )
        ]
        terminal = find_terminal(events)
        if terminal is not None:
            return terminal

        interrupt_id = find_pending(events)
        if interrupt_id is None:
            return None  # no more interrupts and no terminal node -> reached analysis

        new_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=interrupt_id,
                        name=REQUEST_INPUT,
                        response={"answer": "", "skip_remaining": True},
                    )
                )
            ],
        )
    raise AssertionError(f"did not reach a terminal or final state within {MAX_ROUNDS} rounds")


async def check_conversational() -> None:
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    message = types.Content(role="user", parts=[types.Part.from_text(text="Thank you so much!")])
    terminal = await run_until_terminal_or_final(runner, session_id, message)
    assert terminal is not None, "expected a terminal node for pure chit-chat input"
    name, output = terminal
    assert name == "conversational_node", f"expected conversational_node, got {name}: {output!r}"
    assert output == _CONVERSATIONAL_NUDGE, f"expected the fixed nudge text, got: {output!r}"
    print("Conversational-nudge smoke assertion passed.")


async def check_blocked() -> None:
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "I don't have a job right now and no savings at all. "
                    "My rent is $1200 a month."
                )
            )
        ],
    )
    terminal = await run_until_terminal_or_final(runner, session_id, message)
    assert terminal is not None, "expected a terminal node for confirmed no-income-no-savings input"
    name, output = terminal
    assert name == "no_action_node", f"expected no_action_node, got {name}: {output!r}"
    assert output == _NO_INCOME_NO_SAVINGS_BLOCK, f"expected the fixed block text, got: {output!r}"
    print("No-income-no-savings block smoke assertion passed.")


async def check_savings_exemption() -> None:
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "I have no income right now, but I have $15,000 saved in a "
                    "high-yield savings account. My rent is $1200 a month."
                )
            )
        ],
    )
    terminal = await run_until_terminal_or_final(runner, session_id, message)
    assert terminal is None, f"expected no terminal node (should proceed to analysis), got: {terminal}"

    session = await session_service.get_session(app_name="app", user_id="tester", session_id=session_id)
    assert session.state.get("overall_picture"), "expected analysis_pipeline to have run and populated overall_picture"
    print("Savings-exemption smoke assertion passed — proceeded to analysis despite zero income.")


async def check_conversational_never_fires_after_round_zero() -> None:
    """Verifies that conversational_node only fires on round 0, not on round 1+.

    The test targets the bug scenario: if the model somehow returns
    outcome="conversational" on round 1 (even though the intent is round-0-only),
    the code should block it. We can't guarantee the LLM will ask a clarifying
    question vs. returning "conversational" on round 0 (that's model behavior),
    but if we do get to round 1 via a resumed message, conversational_node
    must not fire.

    This test sends a first message that MAY trigger a question, and if so,
    responds with a conversational answer; it then asserts that conversational_node
    does not fire on the resumed round (it either asks another question, proceeds
    to analysis, or hits blocked — anything but conversational_node).
    """
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    # Round 0: send a message with some financial data
    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text="I make about $50k a year and spend maybe $3k a month."
            )
        ],
    )
    events = [
        e
        async for e in runner.run_async(
            user_id="tester", session_id=session_id, new_message=message
        )
    ]

    # Check if round 0 returned a terminal node
    terminal = find_terminal(events)
    if terminal is not None:
        # If a terminal fired on round 0, it's a valid outcome (conversational, blocked, etc.)
        # but we can't test the round-1 scenario, so we pass
        name, output = terminal
        print(f"Conversational-guard smoke assertion passed — round-0 ended with {name}.")
        return

    # Look for a pending question from round 0
    interrupt_id = find_pending(events)
    if interrupt_id is None:
        # No interrupt means it went straight to analysis, also acceptable
        print("Conversational-guard smoke assertion passed — proceeded to analysis from round 0.")
        return

    # We have a question on round 0 — resume with a conversational answer on round 1
    new_message = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=interrupt_id,
                    name=REQUEST_INPUT,
                    response={"answer": "Thanks!", "skip_remaining": False},
                )
            )
        ],
    )

    events = [
        e
        async for e in runner.run_async(
            user_id="tester", session_id=session_id, new_message=new_message
        )
    ]

    # Assert that conversational_node did NOT fire on round 1
    terminal = find_terminal(events)
    if terminal is not None:
        name, output = terminal
        assert (
            name != "conversational_node"
        ), (
            f"conversational_node should only fire on round 0, not on round 1; "
            f"but it fired on resumed answer: {output!r}"
        )
    # If no terminal, it either asked another question or proceeded to analysis, both acceptable

    print(
        "Conversational-guard smoke assertion passed — "
        "round-1 conversational answer does not fire conversational_node."
    )


async def main() -> None:
    await check_conversational()
    await check_blocked()
    await check_savings_exemption()
    await check_conversational_never_fires_after_round_zero()
    print("\nAll intake-gating smoke assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
