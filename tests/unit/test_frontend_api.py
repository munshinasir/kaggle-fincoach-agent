"""Unit tests for frontend/main.py's non-LLM-dependent routes. Anything that
runs the actual Workflow (a real Gemini call) belongs in
tests/smoke/test_frontend_api_smoke.py instead, per this project's testing
conventions (AGENTS.md).
"""

from types import SimpleNamespace

from starlette.testclient import TestClient

from frontend.main import _find_terminal_message, app

client = TestClient(app)


def test_index_serves_the_static_shell():
    response = client.get("/")
    assert response.status_code == 200
    assert "How can I help you today?" in response.text


def test_resume_without_a_pending_session_returns_409():
    response = client.post("/api/resume", json={"session_id": "nonexistent", "answer": "hi"})
    assert response.status_code == 409
    assert response.json()["type"] == "error"


def test_resume_security_without_a_pending_session_returns_409():
    response = client.post("/api/resume-security", json={"session_id": "nonexistent", "proceed": True})
    assert response.status_code == 409
    assert response.json()["type"] == "error"


def test_find_terminal_message_returns_halted_type():
    events = [
        SimpleNamespace(node_info=SimpleNamespace(name="security_checkpoint"), output=None),
        SimpleNamespace(
            node_info=SimpleNamespace(name="halted_node"),
            output="Stopped at your request after a security check.",
        ),
    ]
    assert _find_terminal_message(events) == (
        "halted",
        "Stopped at your request after a security check.",
    )


def test_find_terminal_message_returns_conversational_type():
    events = [
        SimpleNamespace(
            node_info=SimpleNamespace(name="conversational_node"),
            output="Happy to chat! I'm best at building out a full financial picture, though...",
        ),
    ]
    result = _find_terminal_message(events)
    assert result is not None
    assert result[0] == "conversational"


def test_find_terminal_message_returns_blocked_type():
    events = [
        SimpleNamespace(
            node_info=SimpleNamespace(name="no_action_node"),
            output="We can't put together a financial plan right now...",
        ),
    ]
    result = _find_terminal_message(events)
    assert result is not None
    assert result[0] == "blocked"


def test_find_terminal_message_returns_none_when_no_terminal_node_present():
    events = [
        SimpleNamespace(node_info=SimpleNamespace(name="intake_loop"), output=None),
        SimpleNamespace(node_info=SimpleNamespace(name="analysis_pipeline"), output=None),
    ]
    assert _find_terminal_message(events) is None
