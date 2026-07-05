"""Runnable smoke test (NOT pytest) for the frontend's JSON API
(frontend/main.py), exercising a real Gemini call end to end. Confirms
/api/analyze eventually returns a "final" response with both HTML
sections populated, after resuming past any intake-loop clarifying
questions with skip_remaining=True (mirrors the pattern already used in
tests/smoke/test_transaction_fetcher_typed_text_smoke.py).

Run with: uv run python tests/smoke/test_frontend_api_smoke.py
"""

from dotenv import load_dotenv

load_dotenv()

from starlette.testclient import TestClient  # noqa: E402

from frontend.main import app  # noqa: E402

MESSAGE = (
    "My monthly income is 5000, I have 2 dependants. My expenses are: Housing 1500, Food 600, "
    "Transportation 300, Utilities 200, Entertainment 100, Healthcare 80, Personal 120, Other 100. "
    "I have one debt: Credit Card, amount 4000, interest rate 22%, minimum payment 100."
)


def main() -> None:
    client = TestClient(app)

    response = client.post("/api/analyze", data={"message": MESSAGE})
    data = response.json()
    assert response.status_code == 200, data

    for _ in range(4):
        if data["type"] == "final":
            break
        session_id = data["session_id"]
        if data["type"] == "security":
            response = client.post(
                "/api/resume-security", json={"session_id": session_id, "proceed": True}
            )
        else:
            response = client.post(
                "/api/resume",
                json={"session_id": session_id, "answer": "", "skip_remaining": True},
            )
        data = response.json()
        assert response.status_code == 200, data

    assert data["type"] == "final", f"expected a final response within the round cap, got: {data}"
    assert "Your Financial Picture" in data["confirmation_html"]
    assert "Recommendations" in data["recommendations_html"]
    assert "{" not in data["confirmation_html"]
    assert "{" not in data["recommendations_html"]
    print("Frontend API smoke assertions passed — final response reached with both sections rendered.")


if __name__ == "__main__":
    main()
