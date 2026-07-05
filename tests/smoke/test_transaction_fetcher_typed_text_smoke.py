"""Runnable smoke test (NOT pytest) confirming TransactionFetcherAgent's
new skill-based instruction still handles plain typed manual-entry input
correctly (no regression from the inline-instruction version). Uses the
project's standing worked example. Skips past intake_loop's clarifying
question with skip_remaining=True to keep this test focused on
TransactionFetcherAgent's output, not intake behavior (already covered
by Phase 2's own smoke tests).

Run with: uv run python tests/smoke/test_transaction_fetcher_typed_text_smoke.py
"""

import asyncio
import json
import uuid

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import app as adk_app  # noqa: E402

REQUEST_INPUT = "adk_request_input"


def find_pending(events):
    for e in reversed(events):
        if e.content and e.content.parts:
            for p in e.content.parts:
                if p.function_call and p.function_call.name == REQUEST_INPUT:
                    return p.function_call.id
    return None


async def main() -> None:
    session_service = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=session_service)
    session_id = str(uuid.uuid4())
    await session_service.create_session(app_name="app", user_id="tester", session_id=session_id)

    message = (
        "My monthly income is 5000, I have 2 dependants. My expenses are: Housing 1500, Food 600, "
        "Transportation 300, Utilities 200, Entertainment 100, Healthcare 80, Personal 120, Other 100. "
        "I have one debt: Credit Card, amount 4000, interest rate 22%, minimum payment 100."
    )
    new_message = types.Content(role="user", parts=[types.Part.from_text(text=message)])

    fetcher_text = None
    for _ in range(3):
        events = [e async for e in runner.run_async(user_id="tester", session_id=session_id, new_message=new_message)]
        for e in events:
            if e.author == "TransactionFetcherAgent" and e.content and e.content.parts:
                for p in e.content.parts:
                    if p.text:
                        fetcher_text = p.text
        interrupt_id = find_pending(events)
        if interrupt_id is None:
            break
        new_message = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=interrupt_id, name=REQUEST_INPUT, response={"answer": "", "skip_remaining": True}
        ))])

    assert fetcher_text is not None, "TransactionFetcherAgent produced no output"
    parsed = json.loads(fetcher_text)
    assert parsed.get("income") == 5000, f"expected income=5000, got {parsed.get('income')!r}"
    assert "expenses" in parsed and isinstance(parsed["expenses"], dict), "expected an expenses object"
    assert "debts" in parsed, "expected a debts field"
    print("TransactionFetcherAgent output:", json.dumps(parsed, indent=2))
    print("\nTyped-text regression smoke assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
